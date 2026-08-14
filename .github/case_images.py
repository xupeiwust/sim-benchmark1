"""Decide which case images are missing from the registry, and prove none are.

    python .github/case_images.py plan     # -> matrix of images the registry lacks
    python .github/case_images.py verify   # -> exit 1 if any required image is absent

`push-case-images.yaml` used to answer "what do we build?" with `find`: every
directory named `environment/`, every run, unconditionally. That is wrong in
both directions at once, and both directions cost real money.

* **Too wide.** The `find` matched 121 directories, so every push that touched
  any `cases/**/environment/**` path started 121 jobs. Actions meters *per job,
  rounded up to a whole minute*, so a run whose jobs each take ~20 s was billed
  121 minutes. Four such runs in the first three days of August 2026 came to
  456 of this repository's 1074 metered minutes.
* **Too wide in a second way.** 100 of those directories live under
  `cases/_pending/`, `cases/_phase2/` and `cases/_deferred/`, and their
  Dockerfiles start `FROM sim-bench-comsol-6.4:latest` or
  `FROM .../sim-benchmark-base:latest` -- images that exist on no registry. They
  had never once built. The remaining 21 have no Dockerfile at all (an
  `environment/` directory in this repo usually holds the fixtures Harbor
  uploads into the agent's working directory, not a build context), so they
  failed with `failed to read dockerfile`. Every build job in every run since
  at least 2026-04-27 was red.
* **Too narrow.** The obvious repair -- diff `github.event.before..github.sha`
  and build only what the push touched -- narrows the matrix but introduces the
  failure this workflow can least afford: an image that *should* have been
  pushed and was not. `event.before` is all zeroes on the first push to a
  branch and stale after a force-push; a diff that comes back empty is
  indistinguishable from "nothing needed building". Nobody finds out until a
  trial pulls a digest older than the case.

So the matrix is not derived from the push at all. It is derived from the
difference between **what the repository requires** and **what the registry
already has**:

    matrix = { required } - { present in registry }

That is idempotent and stateless. A push that never happened, a run that was
cancelled, a build that failed, a tag deleted by hand -- all of them leave the
same observable, an image the registry lacks, and the next run rebuilds it.
Nothing has to remember anything. `verify` then re-asks the registry after the
builds and fails the run if anything required is still missing, which is what
turns "we missed one" from a silence into a red run.

Two conventions make that difference computable:

* **A required image is one a live track asks for.** `cases/<a>/<b>/<c>/
  environment/Dockerfile` where `<a>` has no leading underscore -- the same
  live-vs-staging split `tools/lint_case.py cases/[!_]*/*/*/` and CI already
  use, so a new track is covered the day it lands and a staging directory never
  is. Today that set is empty: no live case ships an overlay Dockerfile.
* **The tag is the content, not the commit.** `:${{ github.sha }}` changes on
  every commit, which makes "is this image up to date?" unanswerable -- you can
  only ask "does the tag for *this* commit exist", and the answer is no for
  every image on every push. The tag here is `env-<git tree sha of the case's
  environment/>`: it changes exactly when the build context changes, so its
  presence in the registry *is* the up-to-date question.

The one input a content tag does not cover is the base image moving under a
`FROM ...:latest`. There is no cheap signal for that, so it is a manual action:
`workflow_dispatch` with `force=true` rebuilds every required image.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REGISTRY_HOST = "ghcr.io"
# The package namespace is the project's old name and stays put: an image path
# is an identifier, and moving it invalidates every digest already pulled.
IMAGE_PREFIX = "svd-ai-lab/sim-benchmark"

MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


# --------------------------------------------------------------------------
# what the repository requires
# --------------------------------------------------------------------------


def required_cases(repo: Path) -> list[str]:
    """Case paths (relative to `cases/`) that a live track expects an image for.

    A case needs an image only when it ships a build context. Most do not: the
    domain image named by `task.toml`'s `docker_image` is used unmodified, and
    the case's `environment/` holds fixtures instead of a Dockerfile.
    """
    cases = repo / "cases"
    if not cases.is_dir():
        return []
    found = []
    for track in sorted(p for p in cases.iterdir() if p.is_dir()):
        if track.name.startswith("_"):
            continue  # _pending / _phase2 / _deferred / _template are staging
        for dockerfile in sorted(track.glob("*/*/environment/Dockerfile")):
            found.append(dockerfile.parent.parent.relative_to(cases).as_posix())
    return found


def image_slug(case: str) -> str:
    """`cfd/fluids/naca0012_subsonic` -> `cfd-fluids-naca0012_subsonic`."""
    return case.replace("/", "-")


def _git_tree_sha(repo: Path, path: str) -> str:
    out = subprocess.run(
        ["git", "rev-parse", f"HEAD:{path}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def env_tag(repo: Path, case: str, *, tree_sha: Callable[[Path, str], str] = _git_tree_sha) -> str:
    """Content tag for a case's build context.

    The git tree object of `cases/<case>/environment` is exactly "the bytes that
    go into this build", independent of platform and of every unrelated commit.
    """
    sha = tree_sha(repo, f"cases/{case}/environment")
    return f"env-{sha[:12]}"


@dataclass(frozen=True)
class Image:
    case: str
    slug: str
    tag: str

    @property
    def reference(self) -> str:
        return f"{REGISTRY_HOST}/{IMAGE_PREFIX}/{self.slug}:{self.tag}"


def required_images(repo: Path, **kwargs) -> list[Image]:
    return [
        Image(case=case, slug=image_slug(case), tag=env_tag(repo, case, **kwargs))
        for case in required_cases(repo)
    ]


# --------------------------------------------------------------------------
# what the registry already has
# --------------------------------------------------------------------------


class RegistryUnavailable(RuntimeError):
    """The registry did not answer the question, as opposed to answering no."""


def _http_status(url: str, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _http_json(url: str, headers: dict[str, str]) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}


class Registry:
    """Asks ghcr.io whether one tag exists.

    Only two answers are allowed to be quiet, and the split is not cosmetic --
    it decides what the workflow does next:

    * **404 -> absent.** The tag, or the package, is not there. Measured against
      the live namespace: a package this org has never pushed answers 404, while
      one it has answers 403 to a token without `read:packages`. So 404 really
      does mean "nothing to pull", and the right response is to build it.
    * **200 -> present.** Nothing to do.
    * **anything else -> raise.** 401, 403, a 5xx, a token endpoint that refused
      the credentials: the registry declined to answer. Reading that as "absent"
      would queue a rebuild of every required image on a credential problem, and
      then `verify` would fail on the same unreadable answer afterwards -- an
      expensive way to report a broken token. Failing here says what happened.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        get_status: Callable[[str, dict[str, str]], int] = _http_status,
        get_json: Callable[[str, dict[str, str]], tuple[int, dict]] = _http_json,
    ) -> None:
        self._username = username
        self._password = password
        self._get_status = get_status
        self._get_json = get_json

    def _pull_token(self, slug: str) -> str:
        basic = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        scope = f"repository:{IMAGE_PREFIX}/{slug}:pull"
        url = f"https://{REGISTRY_HOST}/token?service={REGISTRY_HOST}&scope={scope}"
        status, payload = self._get_json(url, {"Authorization": f"Basic {basic}"})
        token = payload.get("token") or payload.get("access_token") or ""
        if not token:
            raise RegistryUnavailable(
                f"{REGISTRY_HOST} refused a pull token for {IMAGE_PREFIX}/{slug} "
                f"(HTTP {status}) -- check the job's `packages:` permission"
            )
        return token

    def has(self, slug: str, tag: str) -> bool:
        token = self._pull_token(slug)
        url = f"https://{REGISTRY_HOST}/v2/{IMAGE_PREFIX}/{slug}/manifests/{tag}"
        headers = {"Authorization": f"Bearer {token}", "Accept": MANIFEST_ACCEPT}
        status = self._get_status(url, headers)
        if status == 200:
            return True
        if status == 404:
            return False
        raise RegistryUnavailable(
            f"{REGISTRY_HOST} answered HTTP {status} for {IMAGE_PREFIX}/{slug}:{tag} -- "
            "that is neither present nor absent, so nothing is decided here"
        )


# --------------------------------------------------------------------------
# plan / verify
# --------------------------------------------------------------------------


def missing(images: list[Image], registry: Registry) -> list[Image]:
    return [image for image in images if not registry.has(image.slug, image.tag)]


def _emit(name: str, value: str) -> None:
    print(f"{name}={value}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _report(images: list[Image], absent: list[Image]) -> None:
    absent_slugs = {image.slug for image in absent}
    print(f"required images: {len(images)}")
    for image in images:
        state = "MISSING" if image.slug in absent_slugs else "present"
        print(f"  {state:8} {image.reference}")
    if not images:
        print("  (no live-track case ships an environment/Dockerfile)")


def _registry_from_env() -> Registry:
    password = os.environ.get("GITHUB_TOKEN", "")
    if not password:
        # Guessing "everything is present" would silently publish nothing;
        # guessing "everything is missing" would start a full rebuild. Neither
        # is a safe default for a step whose whole job is to be trusted.
        sys.exit("GITHUB_TOKEN is not set -- cannot ask the registry what it has")
    return Registry(os.environ.get("GITHUB_ACTOR", "x-access-token"), password)


def cmd_plan(args: argparse.Namespace) -> int:
    images = required_images(REPO_ROOT)
    absent = images if args.force else missing(images, _registry_from_env())
    _report(images, absent)
    if args.force and images:
        print("force: rebuilding every required image regardless of the registry")
    _emit("matrix", json.dumps([{"case": i.case, "slug": i.slug, "tag": i.tag} for i in absent]))
    _emit("count", str(len(absent)))
    return 0


def cmd_verify(_: argparse.Namespace) -> int:
    images = required_images(REPO_ROOT)
    absent = missing(images, _registry_from_env())
    _report(images, absent)
    if absent:
        print(
            f"\nFAIL {len(absent)} required image(s) absent after the build step.\n"
            "A push that does not land is the failure this workflow is built to make "
            "loud; re-run it, and if it fails again the build itself is broken.",
            file=sys.stderr,
        )
        return 1
    print("\nok  every required case image is in the registry")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="emit the matrix of images the registry lacks")
    plan.add_argument(
        "--force",
        action="store_true",
        help="put every required image in the matrix, even ones the registry has "
        "(use when a base image moved under a floating FROM tag)",
    )
    plan.set_defaults(func=cmd_plan)

    verify = sub.add_parser("verify", help="fail if any required image is absent")
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RegistryUnavailable as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
