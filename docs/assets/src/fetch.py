"""Download the pinned fonts and icons the diagram generators use into .cache/ (git-ignored), sha256-checked.

Fonts: Inter and JetBrains Mono (SIL OFL 1.1) from @fontsource. Brand icons: Simple Icons (CC0; the marks
belong to their owners). Line icons: Lucide (ISC) and Tabler (MIT).
"""
import hashlib
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")

FS_INTER = "https://cdn.jsdelivr.net/npm/@fontsource/inter@5.1.0/files/inter-latin-%s-normal.woff"
FS_JBM = "https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5.1.0/files/jetbrains-mono-latin-%s-normal.woff"
SI = "https://cdn.jsdelivr.net/npm/simple-icons@15.0.0/icons/%s.svg"
LU = "https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/icons/%s.svg"
TB = "https://cdn.jsdelivr.net/npm/@tabler/icons@3.24.0/icons/outline/%s.svg"

ASSETS = {  # cache path: (url, sha256)
    "fonts/inter-400.woff": (FS_INTER % 400, "31656ddbb58d39790f910df827596106a5d91ce80dd4309a6aad91e08a90f9e4"),
    "fonts/inter-500.woff": (FS_INTER % 500, "e7e967e71a1e3afcefab9bb798ecc34f810a0c9b3a1e4d1bec2de15b86417cea"),
    "fonts/inter-600.woff": (FS_INTER % 600, "a96e5ee7ab248008e5e6cc92dd561eceb892d19a10a537aa1b2e64f979351add"),
    "fonts/inter-700.woff": (FS_INTER % 700, "82b0531fe0abacf8ab159cc00c7d7b637bd1685130cdab0dea837b39a0ffa743"),
    "fonts/jbm-400.woff": (FS_JBM % 400, "f1ba9869ce1e6ebd291c8cbe38be69f4644664680965b978eedb576cb9b19e28"),
    "fonts/jbm-600.woff": (FS_JBM % 600, "dbb81eaf14c1981193e9a16b5ce51e595b8cfef9be38476039b6d4bcf7b3de83"),
    "icons/si-blender.svg": (SI % "blender", "ec86e2c9cf9fc25f5c8d3bf2e8d201c0dce6683137f37a1e61f992da6566bff5"),
    "icons/si-claude.svg": (SI % "claude", "2d6fda79eb18ddccca35b799eeb3cece0dfabc22520ce3b10abd25668df9fa93"),
    "icons/si-meta.svg": (SI % "meta", "e3e9db62f59dc477e5917687349b8aa9685b841d40300c1afad60ad85075cd2e"),
    "icons/si-unity.svg": (SI % "unity", "b5b66fda997db7445483ff2917b1c17abb8da607d43905835551991aeb940753"),
    "icons/tb-cardboards.svg": (TB % "cardboards", "5bc7bed356d7d71d7569038cd9f9e570b6bde5d360e1e3b74ae4357a758c1faa"),
    "icons/lu-box.svg": (LU % "box", "bec443177a99fa4db4389d5953144debd1fec00aa4550d8bae1e9a1e2727a7a5"),
    "icons/lu-camera.svg": (LU % "camera", "5388c29f288d9e94d9f927a85a6319fd1d73a49993184bfa0a1237aa64ef0b13"),
    "icons/lu-code-xml.svg": (LU % "code-xml", "1bdde654ff1dfcab351cb51a9365799a7daebed70941c27de8b8c0d0f74bfa0a"),
    "icons/lu-list-checks.svg": (LU % "list-checks", "a0ce5eff7f65bac7fdffebcff850c2cd4dedd28141822729b236526f1c7656a9"),
    "icons/lu-lock-keyhole.svg": (LU % "lock-keyhole", "f136ce885db37b7628684b733701331d98c0f307908f248172cbee8514e706f3"),
    "icons/lu-mouse-pointer-click.svg": (LU % "mouse-pointer-click", "116a7c8a962a85467e9464a1b055b8b649def2257fe4a30c186efc740b0f989f"),
    "icons/lu-refresh-cw.svg": (LU % "refresh-cw", "37b0bfd29e4860483c533abd85c7bb5bc87a8478492b9b69f90e77ddfdc3d222"),
    "icons/lu-rocket.svg": (LU % "rocket", "2e24d9b9ba9a0df601d8b1e254c6457d16dd1738d3981a3a51817f14dcc5cf0c"),
    "icons/lu-search.svg": (LU % "search", "a63f719fd335dc94079199dd9f3c2538e886d25e6ca1555bcd1d0bd58c2ec3b6"),
    "icons/lu-shield-check.svg": (LU % "shield-check", "dac94580040be3514ef31b575a6f92e4576607786e76b94a8df80d2accc890ce"),
    "icons/lu-sun.svg": (LU % "sun", "54bf3c49f788d2dcdd39753f118ad3e1ba325886d62382903139bfefc16ff433"),
}


def main():
    bad = 0
    for rel, (url, want) in ASSETS.items():
        path = os.path.join(CACHE, rel)
        if os.path.isfile(path) and hashlib.sha256(open(path, "rb").read()).hexdigest() == want:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = urllib.request.urlopen(url, timeout=60).read()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            print("sha256 mismatch for %s (%s): got %s" % (rel, url, got))
            bad += 1
            continue
        open(path, "wb").write(data)
        print("fetched", rel)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
