#!/bin/bash
# ACE-Step 1.5 安装器：仅在本机安装；不修改 VPN、系统代理或 shell 配置。
# 用法：bash install-acestep-macos.sh [--plan|--install|--start]
set -euo pipefail
umask 077

SOURCE_COMMIT=ca1e85fe9430179831e6bc6be790c332190a3866
MODEL_REPO=ACE-Step/Ace-Step1.5
ROOT=${ACE_INSTALL_DIR:-"$HOME/ace-step-local"}
ATTEMPTS=${ACE_RETRIES:-3}
MODE=${1:---install}

case "$ROOT" in /*) ;; *) echo "ACE_INSTALL_DIR 必须是绝对路径。" >&2; exit 2;; esac
case "$ATTEMPTS" in [1-5]) ;; *) echo "ACE_RETRIES 请使用 1–5。" >&2; exit 2;; esac
[ "$#" -le 1 ] || { echo "只接受一个操作参数。" >&2; exit 2; }

SRC="$ROOT/source-$SOURCE_COMMIT"
BIN="$ROOT/bin"
export UV_CACHE_DIR="$ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/cache/python"
export UV_PROJECT_ENVIRONMENT="$ROOT/venvs/$SOURCE_COMMIT"
export UV_HTTP_RETRIES=2 UV_HTTP_TIMEOUT=90
export HF_HOME="$ROOT/cache/huggingface"
export HF_HUB_DISABLE_XET=1 HF_HUB_ETAG_TIMEOUT=30 HF_HUB_DOWNLOAD_TIMEOUT=90
export HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 GRADIO_ANALYTICS_ENABLED=False
export ACESTEP_PROJECT_ROOT="$SRC"
export ACESTEP_CHECKPOINTS_DIR="$ROOT/checkpoints"
export PATH="$BIN:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
export ACE_INSTALL_ROOT="$ROOT" ACE_MODEL_REPO="$MODEL_REPO"
# User proxies inherited unchanged during installation; let local clients bypass them.
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}localhost,127.0.0.1"
export no_proxy="${no_proxy:+$no_proxy,}localhost,127.0.0.1"

die() { printf '%s\n' "$*" >&2; exit 1; }
retry() {
  local stage=$1 attempt=1 code
  shift
  while :; do
    printf '\n[%s] 第 %s/%s 次\n' "$stage" "$attempt" "$ATTEMPTS" >&2
    if "$@"; then return 0; else code=$?; fi
    if [ "$attempt" -ge "$ATTEMPTS" ]; then
      printf '[%s] 失败（退出码 %s），保留已有文件和缓存。若是网络问题，换到 VPN 后重新运行相同安装命令。\n' "$stage" "$code" >&2
      return "$code"
    fi
    sleep "$((attempt * 3))"
    attempt="$((attempt + 1))"
  done
}

plan() {
  cat <<EOF
平台：Apple Silicon macOS；不需要 sudo，不会改代理/VPN。
目标：$ROOT
源码：ACE-Step/ACE-Step-1.5 @ $SOURCE_COMMIT
模型：$MODEL_REPO 的 Turbo、VAE、文本编码器及包内 1.7B。
官方模型包约 10.1 GB，不另下 0.6B；源码和 Python 依赖另计。全新环境建议预留 11–12 GB 流量。
第一次安装解析并记住模型版本；同一目录重跑不会更新版本。
安装：bash install-acestep-macos.sh --install
启动：bash install-acestep-macos.sh --start
可选：ACE_INSTALL_DIR 指定同一个安装目录，ACE_RETRIES=1-5（默认 3）。
--plan 只打印，不联网，不写文件。
EOF
}

write_models_helper() {
  cat >"$ROOT/models.py" <<'PY'
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

root = Path(os.environ["ACE_INSTALL_ROOT"])
repo = os.environ["ACE_MODEL_REPO"]
models = Path(os.environ["ACESTEP_CHECKPOINTS_DIR"])
manifest_file = root / "model-manifest.json"
groups = ("acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B", "acestep-5Hz-lm-1.7B")


def fail(message):
    raise SystemExit(message)


def save_json(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def check_manifest(meta):
    if meta.get("repo") != repo or not re.fullmatch("[0-9a-f]{40}", meta.get("revision", "")):
        fail("已有模型清单的仓库或版本无效；请保留现有数据，并用单独目录安装。")
    files = meta.get("files") or {}
    for name, data in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name != str(path) or len(path.parts) < 2 or path.parts[0] not in groups:
            fail(f"模型清单路径非法：{name}")
        if not isinstance(data.get("size"), int) or data["size"] < 0:
            fail(f"大小缺失：{name}")
        digest = data.get("sha256")
        if digest and not re.fullmatch("[0-9a-f]{64}", digest):
            fail(f"SHA-256 无效：{name}")
        if path.suffix in {".pt", ".safetensors", ".bin"} and not digest:
            fail(f"权重缺少 SHA-256：{name}")
    total = sum(item["size"] for item in files.values())
    if total > 11_000_000_000:
        fail(f"模型清单为 {total / 1e9:.2f} GB，超出脚本 11 GB 的模型安全上限，不下载。")
    for group in groups:
        if not any(name.startswith(group + "/") and name.endswith(".safetensors") for name in files):
            fail(f"模型清单缺少 {group} 的权重；不下载。")
    return files


def get_manifest(install):
    if manifest_file.exists():
        meta = json.loads(manifest_file.read_text())
        check_manifest(meta)
        return meta
    if not install:
        fail("还没有模型清单，请先运行 --install。")
    from huggingface_hub import HfApi
    info = HfApi(endpoint="https://huggingface.co").model_info(repo, revision="main", files_metadata=True)
    files = {}
    for item in info.siblings:
        if item.rfilename.split("/", 1)[0] not in groups:
            continue
        lfs = item.lfs
        digest = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
        files[item.rfilename] = {"size": item.size, "sha256": digest}
    meta = {"repo": repo, "revision": info.sha, "files": files}
    check_manifest(meta)
    save_json(manifest_file, meta)
    return meta


def on_disk(files, verify_weights):
    missing = []
    for name, item in files.items():
        path = models / name
        if not path.is_file() or path.stat().st_size != item["size"]:
            missing.append(name)
            continue
        if verify_weights and item["sha256"]:
            with path.open("rb") as f:
                correct = hashlib.file_digest(f, "sha256").hexdigest() == item["sha256"]
            if not correct:
                # Move aside the bad final file so the next run cannot mistake it for cached.
                path.replace(path.with_name(path.name + ".bad"))
                missing.append(name)
    return missing


install = sys.argv[1] == "install"
manifest = get_manifest(install)
files = manifest["files"]
if not install:
    missing = on_disk(files, False)
    if missing:
        fail(f"缺少 {len(missing)} 个模型文件（例如 {missing[0]}）；请先运行 --install。")
else:
    print(f"固定模型版本：{manifest['revision']}；清单共 {sum(x['size'] for x in files.values()) / 1e9:.2f} GB。", flush=True)
    needed = on_disk(files, True)
    if not needed:
        print("模型文件已完整且已校验，跳过下载。")
        sys.exit(0)
    print(f"待补齐 {len(needed)} 个文件；未完成文件尽量从本地缓存续传。", flush=True)
    from huggingface_hub import hf_hub_download
    # Exact paths, no auxiliary 0.6B LM and no accidental full-repo snapshot.
    for name in needed:
        print(f"下载：{name}（{files[name]['size'] / 1e6:.2f} MB）", flush=True)
        hf_hub_download(repo_id=repo, filename=name, revision=manifest["revision"],
                        endpoint="https://huggingface.co", local_dir=models)
    missing = on_disk(files, True)
    if missing:
        fail(f"尚有 {len(missing)} 个文件未通过校验（例如 {missing[0]}）。")
    print("全部模型已安装并通过校验。")
PY
}

case "$MODE" in
  --plan|--help|-h) plan; exit 0 ;;
  --install|--start) ;;
  *) plan >&2; exit 2 ;;
esac

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] ||
  die "请在 Apple Silicon 的 Mac 上用原生 arm64 终端运行。"

if [ "$MODE" = --start ]; then
  [ -f "$ROOT/.installed-$SOURCE_COMMIT" ] && [ -x "$UV_PROJECT_ENVIRONMENT/bin/acestep" ] ||
    die "还没有完成安装，请先运行 --install。"
  cd "$SRC"
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 UV_OFFLINE=1
  "$UV_PROJECT_ENVIRONMENT/bin/python" "$ROOT/models.py" check
  echo "浏览器访问 http://127.0.0.1:7860；按 Ctrl+C 停止。"
  exec "$UV_PROJECT_ENVIRONMENT/bin/acestep" --server-name 127.0.0.1 --port 7860 --language zh \
    --config_path acestep-v15-turbo --init_llm true --lm_model_path acestep-5Hz-lm-1.7B \
    --backend mlx --init_service true
fi

mkdir -p "$ROOT" "$ROOT/cache" "$BIN"
LOCK="$ROOT/.install-running"
mkdir "$LOCK" 2>/dev/null || die "已有安装进程，或上次被强制终止。确认没有进程后，可删除空目录 '$LOCK' 再重试。"
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fetch_small() {
  # Small installer/archive only. Large weights are resumed by Hugging Face.
  local url=$1 target=$2
  if [ -s "$target" ]; then return 0; fi
  curl --proto '=https' --proto-redir '=https' --fail --location --show-error \
    --connect-timeout 20 --speed-limit 1024 --speed-time 30 -o "$target.part" "$url" &&
    mv "$target.part" "$target"
}

if ! command -v uv >/dev/null 2>&1; then
  installer="$ROOT/cache/uv-install.sh"
  retry "下载 uv 安装器" fetch_small "https://astral.sh/uv/install.sh" "$installer"
  retry "安装 uv" env UV_UNMANAGED_INSTALL="$BIN" UV_NO_MODIFY_PATH=1 /bin/sh "$installer"
  [ -x "$BIN/uv" ] || die "uv 安装器未在预期位置生成可执行文件。"
fi

if [ ! -f "$SRC/uv.lock" ] || [ ! -f "$SRC/pyproject.toml" ]; then
  archive="$ROOT/cache/$SOURCE_COMMIT.tar.gz"
  retry "下载官方源码" fetch_small "https://codeload.github.com/ace-step/ACE-Step-1.5/tar.gz/$SOURCE_COMMIT" "$archive"
  temp="$(mktemp -d "$ROOT/source-stage.XXXXXX")"
  if ! tar -xzf "$archive" -C "$temp" --strip-components=1; then
    mv "$archive" "$archive.bad"
    die "源码压缩包校验未通过，已保留坏包，重跑会重新下载源码。"
  fi
  [ -f "$temp/pyproject.toml" ] && [ -f "$temp/uv.lock" ] || die "源码没有预期的项目文件，未执行安装。"
  [ ! -e "$SRC" ] || die "官方源码目录已存在但不完整；请移走旧目录，再运行脚本。"
  mv "$temp" "$SRC"
fi

cd "$SRC"
retry "安装 Python 3.12 和依赖" uv sync --locked --python 3.12
write_models_helper
retry "下载并校验模型" "$UV_PROJECT_ENVIRONMENT/bin/python" "$ROOT/models.py" install
touch "$ROOT/.installed-$SOURCE_COMMIT"
printf '\n安装完成，未自动启动。运行：bash "%s" --start\n' "$0"
