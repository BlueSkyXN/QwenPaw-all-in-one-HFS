#!/usr/bin/env python3
"""HFS v3.0 静态对齐检查器（示例实现，不强制）。

退出码：
  0：检查通过（可有 WARN/NOTE）。
  1：存在 ERROR。ERROR 是已确认踩不可豁免边界中的可静态判断项。
  2：检测到旧标准（2.1/2.2）项目，只读输出迁移差距报告；或输入错误。

WARN：偏离默认指导，不阻断；登记 deviations 后降为 NOTE。
NOTE：信息或需要人工确认的事项。

本工具不能证明 Space 仓没有闭源源码，也不能证明启动流程完全 fail-closed；
这两项仍需项目级 review 和 smoke。
"""

from __future__ import annotations

import argparse
import re
import stat
import subprocess
import sys
import tomllib
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any


SUPPORTED_STANDARDS = {"3.0"}
DEFAULT_STANDARD = "3.0"
LEGACY_STANDARDS = {"2.1", "2.2"}
REQUIRED_FIELDS = (
    "project",
    "space",
    "space_visibility",
    "bucket_visibility",
    "project_class",
    "target_role",
    "sovereignty",
    "lane",
    "version_source",
    "env_file",
)
ROOT_LEVEL_FIELDS = {
    "standard",
    "project",
    "space",
    "space_visibility",
    "bucket_visibility",
    "project_class",
    "target_role",
    "sovereignty",
    "lane",
    "version_source",
    "bucket_namespace",
    "local_only",
    "secrets",
    "optional_secrets",
    "variables",
    "env_file",
    "dist_bucket",
    "seed_file",
    "other_objects",
    "mount_config_bucket",
    "mount_config_object",
    "deviations",
    "compat",
}
SOVEREIGNTIES = {"sovereign", "fork", "port"}
LANES = {"source", "artifact"}
VERSION_SOURCES = {"latest", "tag", "commit"}
PROJECT_CLASSES = {"preview", "production"}
TARGET_ROLES = {"primary", "rotation", "candidate", "restore"}
SPACE_VISIBILITIES = {"protected"}
BUCKET_VISIBILITIES = {"private"}
DEFAULT_SEED_FILE = "config.toml"
CONFIG_SCHEMA = {
    "app": ("environment", "log_level"),
    "server": ("host", "port"),
    "storage": ("data_dir",),
    "auth": ("mode", "admin_enabled"),
}
CONFIG_OPTIONAL_SECTIONS = {"features"}
SENSITIVE_KEY_SUFFIXES = {
    "pass",
    "password",
    "passwd",
    "passphrase",
    "pwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "private_key",
    "client_secret",
    "credential",
    "credentials",
}
SAFE_PLACEHOLDERS = {"__FROM_ENV__", "CHANGE_ME", "REPLACE_ME", "REDACTED", "<SECRET>"}
ANGLE_PLACEHOLDER = re.compile(
    r"^<[^<>]*(?:placeholder|secret|token|password|passphrase|api[-_ ]?key|"
    r"replace|change|example|sample|todo|value)[^<>]*>$",
    flags=re.IGNORECASE,
)
URL_VALUE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"']+")
DSN_FIELD = re.compile(
    r"(?:^|[\s;])(?P<key>[A-Za-z][A-Za-z0-9_.-]*)\s*=\s*(?P<value>[^\s;]+)"
)
REDLINE_RULES = {
    "secret-in-git",
    "version-source-explicit",
    "closed-source-in-space",
    "fail-closed",
    "local-plaintext-source",
    "project-class-explicit",
    "target-role-explicit",
    "space-visibility-protected",
    "bucket-visibility-private",
}
SAFE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_LOCAL_ONLY = {"HF_TOKEN", "GH_TOKEN"}

BASE_IMAGES = {
    "scratch",
    "debian",
    "ubuntu",
    "alpine",
    "busybox",
    "python",
    "node",
    "golang",
    "rust",
    "openjdk",
    "eclipse-temurin",
    "php",
    "ruby",
    "perl",
}

SECRET_VALUE = re.compile(
    r"(hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
)
DATE_IN_NAME = re.compile(r"20\d{2}(?:[-_.]?\d{2})?")
ARG_LINE = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)(?:=(.*))?\s*$")
FROM_LINE = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+[Aa][Ss]\s+(\S+))?\s*$")
VARIABLE_REF = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")


class Report:
    def __init__(self, deviations: dict[str, str]) -> None:
        self.deviations = deviations
        self.errors = 0
        self.warnings = 0

    def error(self, rule: str, message: str) -> None:
        self.errors += 1
        print(f"ERROR [{rule}] {message}")

    def warn(self, rule: str, message: str) -> None:
        if rule in REDLINE_RULES:
            self.error(rule, message)
            return
        if rule in self.deviations:
            print(f"NOTE  [{rule}] {message}（已登记例外：{self.deviations[rule]}）")
            return
        self.warnings += 1
        print(f"WARN  [{rule}] {message}")

    def note(self, rule: str, message: str) -> None:
        print(f"NOTE  [{rule}] {message}")


def forbidden_key_reason(name: str) -> str | None:
    """v3.0 禁止登记的旧式键名；返回原因，合法时返回 None。

    SMOKE_* 开头的键视为真实独立 smoke 身份，不在禁止之列；
    只有 产品前缀 + SMOKE 场景词（如 SOUWEN_SMOKE_BEARER_TOKEN）被禁止。
    """
    if name.startswith(("SHOWCASE_", "BOOTSTRAP_")) or "_SHOWCASE_" in name or "_BOOTSTRAP_" in name:
        return "包含已禁止的 SHOWCASE/BOOTSTRAP 场景词"
    if "_SMOKE_" in name:
        return "包含已禁止的 产品前缀 + SMOKE 场景词；真实独立 smoke 身份使用 SMOKE_ 开头"
    if name != "ADMIN_PASSWORD" and name.endswith("_ADMIN_PASSWORD"):
        return "禁止产品前缀管理员密码键；统一使用 ADMIN_PASSWORD"
    if name != "OPS_TOKEN" and name.endswith("_OPS_TOKEN"):
        return "禁止产品前缀运维键；统一使用 OPS_TOKEN"
    return None


def find_manifest(root: Path) -> tuple[Path | None, str | None]:
    primary = root / "hfs-dev.toml"
    if primary.exists():
        return primary, None
    legacy = root / "cloud" / "hfs" / "hfs-dev.toml"
    if legacy.exists():
        return legacy, "manifest 位于 cloud/hfs/；v2 默认建议放项目根，但旧仓可逐步迁移"
    return None, None


def parse_manifest(path: Path | None) -> tuple[dict[str, Any], str | None, str | None]:
    if path is None:
        return {}, None, None
    raw = path.read_text(encoding="utf-8")
    try:
        return tomllib.loads(raw), raw, None
    except tomllib.TOMLDecodeError as exc:
        return {}, raw, str(exc)


def string_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return value
    return None


def string_map(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    if not all(
        isinstance(source, str) and source and isinstance(target, str) and target
        for source, target in value.items()
    ):
        return None
    return dict(value)


def parse_deviations(manifest: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    result: dict[str, str] = {}
    malformed: list[str] = []
    values = manifest.get("deviations", [])
    if not isinstance(values, list):
        return result, ["deviations 不是字符串数组"]
    for entry in values:
        if not isinstance(entry, str) or "=" not in entry:
            malformed.append(str(entry))
            continue
        rule, reason = entry.split("=", 1)
        rule, reason = rule.strip(), reason.strip()
        if not rule or not reason:
            malformed.append(entry)
            continue
        result[rule] = reason
    return result, malformed


def misplaced_root_fields(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    """Return known manifest keys that TOML parsed below a table.

    TOML permits an otherwise-valid key below any table.  That is especially
    easy to miss for ``version_source``: the parsed document is valid, but the
    checker treats the root field as absent and emits an unhelpful generic
    error.  HFS manifests deliberately have a flat schema, so every known
    field found below a table is a placement error.
    """

    found: list[tuple[str, str]] = []

    def visit(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if path and key in ROOT_LEVEL_FIELDS:
                    found.append((key, ".".join((*path, key))))
                visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(manifest, ())
    return found


def git_available(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_tracked(root: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", str(relative)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def git_ignored(root: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", "--no-index", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def valid_relative_path(value: Any) -> PurePosixPath | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        return None
    return path


def valid_env_file(value: Any) -> PurePosixPath | None:
    path = valid_relative_path(value)
    if path is None:
        return None
    if str(path) == ".env":
        return path
    if len(path.parts) == 3 and path.parts[:2] == ("local", "hfs-targets") and path.suffix == ".env":
        return path
    return None


def has_symlink_component(root: Path, relative: PurePosixPath) -> bool:
    current = root.resolve()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def check_plaintext_file(
    report: Report,
    root: Path,
    relative: PurePosixPath,
    *,
    require_local_values: bool,
) -> None:
    path = root.joinpath(*relative.parts)
    if has_symlink_component(root, relative):
        report.error("local-plaintext-source", f"本地明文事实源不能包含 symlink：{relative}")
        return
    if not path.exists():
        if require_local_values:
            report.error("local-plaintext-source", f"缺少本地明文事实源：{relative}")
        else:
            report.note("local-plaintext-source", f"本地明文事实源未出现在当前 checkout：{relative}")
        return
    if not path.is_file():
        report.error("local-plaintext-source", f"本地明文事实源必须是普通文件：{relative}")
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        report.error(
            "local-plaintext-source",
            f"本地明文事实源权限必须是 0600，当前为 {mode:04o}：{relative}",
        )


def env_key_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key = line.partition("=")[0].strip()
        if ENV_KEY.fullmatch(key):
            names.add(key)
    return names


def declared_profile_env_files(root: Path) -> set[Path]:
    declared: set[Path] = set()
    for manifest_path in root.glob("hfs-dev*.toml"):
        try:
            with manifest_path.open("rb") as file:
                profile = tomllib.load(file)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        relative = valid_env_file(profile.get("env_file"))
        if relative is not None:
            declared.add(root.joinpath(*relative.parts).resolve())
    return declared


def check_git_hygiene(
    report: Report,
    root: Path,
    manifest: dict[str, Any],
    *,
    require_local_values: bool,
) -> None:
    git_ok = git_available(root)
    if not git_ok:
        report.warn("git-source-missing", "当前目录不是 Git 工作树，无法建立可审计的代码事实源")

    env_relative = valid_env_file(manifest.get("env_file"))
    if env_relative is not None:
        env_path = root.joinpath(*env_relative.parts)
        if git_ok and git_tracked(root, env_path):
            report.error("secret-in-git", f"{env_relative} 已被 Git 跟踪（密码、密钥不得进入 Git）")
        if git_ok and not git_ignored(root, str(env_relative)):
            report.warn("local-ledger-ignore", f"{env_relative} 未被 Git ignore，容易被误提交")
        check_plaintext_file(
            report,
            root,
            env_relative,
            require_local_values=require_local_values,
        )

        registered = set()
        for field in ("local_only", "secrets", "optional_secrets", "variables"):
            values = string_list(manifest.get(field, []))
            if values is not None:
                registered.update(values)
        candidates = list(root.glob(".env*")) + list((root / "local" / "hfs-targets").glob("*.env"))
        profile_paths = declared_profile_env_files(root)
        duplicates: list[str] = []
        for candidate in candidates:
            if candidate.name.endswith((".example", ".sample", ".template")):
                continue
            if candidate.resolve() == env_path.resolve() or candidate.resolve() in profile_paths or not candidate.is_file():
                continue
            if env_key_names(candidate) & registered:
                duplicates.append(str(candidate.relative_to(root)))
        if duplicates:
            report.error(
                "local-plaintext-source",
                f"发现包含登记键的第二 env 事实源：{sorted(set(duplicates))}",
            )

    seed_value = manifest.get("seed_file", DEFAULT_SEED_FILE)
    if git_ok and isinstance(seed_value, str) and seed_value:
        seed = root / seed_value
        standard_config = seed_value == DEFAULT_SEED_FILE
        if git_tracked(root, seed) and not standard_config:
            report.warn("seed-file-tracked", f"真实种子文件已被 Git 跟踪：{seed_value}；应提交无密模板而不是真实配置")
        if not standard_config and not git_ignored(root, seed_value):
            report.warn("local-ledger-ignore", f"种子文件未被 Git ignore：{seed_value}")
    if git_ok and not git_ignored(root, "local/"):
        report.warn("local-ledger-ignore", "local/ 未被 Git ignore；同步备份和本地审计材料可能被误提交")


def check_manifest(
    report: Report,
    path: Path | None,
    location_note: str | None,
    manifest: dict[str, Any],
    raw: str | None,
    parse_error: str | None,
    malformed_deviations: list[str],
) -> None:
    if path is None:
        report.warn("manifest-missing", "缺少 hfs-dev.toml；旧仓可逐步迁移，但同步脚本无法运行")
        report.error("project-class-explicit", "缺少 manifest，不能确认项目是 preview 还是 production")
        report.error("target-role-explicit", "缺少 manifest，不能确认 Space 角色")
        report.error("space-visibility-protected", "缺少 manifest，不能确认 Space 为 Protected")
        report.error("bucket-visibility-private", "缺少 manifest，不能确认 bucket 为 Private")
        report.error("local-plaintext-source", "缺少 manifest，不能确认本地明文事实源")
        report.error(
            "version-source-explicit",
            "缺少 manifest，不能确认 version_source（latest、tag、commit 三选一）",
        )
        return
    if location_note:
        report.note("manifest-location", location_note)
    if parse_error is not None:
        report.warn("manifest-schema", f"{path} TOML 解析失败：{parse_error}")
        if raw is not None and SECRET_VALUE.search(raw):
            report.error("secret-in-git", f"{path} 疑似包含真实 token")
        report.error(
            "project-class-explicit",
            "manifest 无法解析，不能确认项目是 preview 还是 production",
        )
        report.error(
            "target-role-explicit",
            "manifest 无法解析，不能确认 Space 角色",
        )
        report.error(
            "space-visibility-protected",
            "manifest 无法解析，不能确认 Space 为 Protected",
        )
        report.error(
            "bucket-visibility-private",
            "manifest 无法解析，不能确认 bucket 为 Private",
        )
        report.error(
            "local-plaintext-source",
            "manifest 无法解析，不能确认本地明文事实源",
        )
        report.error(
            "version-source-explicit",
            "manifest 无法解析，不能确认 version_source（latest、tag、commit 三选一）",
        )
        return
    if raw is not None and SECRET_VALUE.search(raw):
        report.error("secret-in-git", f"{path} 疑似包含真实 token；manifest 只能登记名称")

    for field, nested_path in misplaced_root_fields(manifest):
        report.warn(
            "manifest-schema",
            f"根级字段 {field!r} 被误放入 table：{nested_path}；必须位于 hfs-dev.toml 根级",
        )

    standard = str(manifest.get("standard", ""))
    if standard not in SUPPORTED_STANDARDS:
        report.error(
            "manifest-schema",
            f"standard 应为 \"3.0\"，当前为 {manifest.get('standard', '未声明')!r}；"
            "2.1/2.2 项目请按 README「从 2.1/2.2 迁移」配方人工升级",
        )
    for field in REQUIRED_FIELDS:
        if field == "version_source":
            continue
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            report.warn("manifest-schema", f"缺少有效字段：{field}")

    sovereignty = manifest.get("sovereignty")
    if isinstance(sovereignty, str) and sovereignty not in SOVEREIGNTIES:
        report.warn("manifest-schema", f"sovereignty={sovereignty!r} 非法：sovereign=自研、fork=二开、port=移植")
    lane = manifest.get("lane")
    if isinstance(lane, str) and lane not in LANES:
        report.warn("manifest-schema", f"lane={lane!r} 非法：source=源码车道、artifact=成品车道")
    version_source = manifest.get("version_source")
    if not isinstance(version_source, str) or not version_source:
        report.error("version-source-explicit", "缺少有效字段：version_source（latest、tag、commit 三选一）")
    elif version_source not in VERSION_SOURCES:
        report.error("version-source-explicit", f"version_source={version_source!r} 非法：latest、tag、commit 三选一")
    elif version_source == "latest":
        report.note("version-source-explicit", "version_source=latest 是显式选择；项目需接受自动漂移风险")
    project_class = manifest.get("project_class")
    if not isinstance(project_class, str) or project_class not in PROJECT_CLASSES:
        report.error(
            "project-class-explicit",
            f"project_class={project_class!r} 非法：preview、production 二选一",
        )
    target_role = manifest.get("target_role")
    if not isinstance(target_role, str) or target_role not in TARGET_ROLES:
        report.error(
            "target-role-explicit",
            f"target_role={target_role!r} 非法：primary、rotation、candidate、restore 四选一",
        )
    space_visibility = manifest.get("space_visibility")
    if not isinstance(space_visibility, str) or space_visibility not in SPACE_VISIBILITIES:
        report.error(
            "space-visibility-protected",
            f"space_visibility={space_visibility!r} 非法：HFS Space 必须显式为 protected",
        )
    bucket_visibility = manifest.get("bucket_visibility")
    if not isinstance(bucket_visibility, str) or bucket_visibility not in BUCKET_VISIBILITIES:
        report.error(
            "bucket-visibility-private",
            f"bucket_visibility={bucket_visibility!r} 非法：HFS bucket 必须显式为 private",
        )

    env_file = manifest.get("env_file")
    if valid_env_file(env_file) is None:
        report.error(
            "local-plaintext-source",
            "env_file 只能是项目根 .env 或 local/hfs-targets/<profile>.env",
        )
    if "secret_files" in manifest:
        report.error(
            "manifest-schema",
            "secret_files 已在 v3.0 移除：机密只登记 .env；"
            "确需原生结构化文件时，由 wrapper 从标准 .env 生成到 local/generated/",
        )
    if "env_map" in manifest:
        report.error(
            "manifest-schema",
            "env_map 已移动到 [compat.env_map]；sovereign 项目禁止使用映射",
        )
    unknown_root_fields = sorted(
        set(manifest) - ROOT_LEVEL_FIELDS - {"secret_files", "env_map"}
    )
    if unknown_root_fields:
        report.error(
            "manifest-schema",
            f"hfs-dev.toml 含未知根字段：{unknown_root_fields}",
        )

    project = manifest.get("project")
    if isinstance(project, str) and not SAFE_SLUG.fullmatch(project):
        report.warn("manifest-schema", f"project 不是安全的单段名称：{project!r}")
    space = manifest.get("space")
    if isinstance(space, str) and space:
        space_slug = space.rsplit("/", 1)[-1]
        if DATE_IN_NAME.search(space_slug):
            report.warn("name-no-date", f"Space slug={space_slug!r} 含日期；短期轮换项目请登记例外")

    secrets = string_list(manifest.get("secrets", []))
    optional_secrets = string_list(manifest.get("optional_secrets", []))
    variables = string_list(manifest.get("variables", []))
    local_only = string_list(manifest.get("local_only", []))
    for field, value in (
        ("secrets", secrets),
        ("optional_secrets", optional_secrets),
        ("variables", variables),
        ("local_only", local_only),
    ):
        if value is None:
            report.warn("manifest-schema", f"{field} 必须是字符串数组")
        else:
            invalid_names = sorted(name for name in value if not ENV_KEY.fullmatch(name))
            if invalid_names:
                report.warn("manifest-schema", f"{field} 含非法环境变量键名：{invalid_names}")
            duplicates = sorted({name for name in value if value.count(name) > 1})
            if duplicates:
                report.warn("manifest-schema", f"{field} 存在重复项：{duplicates}")
    if secrets is not None and optional_secrets is not None:
        overlap = set(secrets) & set(optional_secrets)
        if overlap:
            report.warn(
                "manifest-schema",
                f"同一键同时登记为 required secret 和 optional secret：{sorted(overlap)}",
            )
    if secrets is not None and optional_secrets is not None and variables is not None:
        overlap = (set(secrets) | set(optional_secrets)) & set(variables)
        if overlap:
            report.warn(
                "manifest-schema",
                f"同一键同时登记为 secret/optional secret 和 variable：{sorted(overlap)}",
            )
    if (
        local_only is not None
        and secrets is not None
        and optional_secrets is not None
        and variables is not None
    ):
        local_only_names = DEFAULT_LOCAL_ONLY | set(local_only)
        overlap = local_only_names & (
            set(secrets) | set(optional_secrets) | set(variables)
        )
        if overlap:
            report.warn(
                "manifest-schema",
                "本地控制凭据同时被登记为 Space secret/optional/variable 设置："
                f"{sorted(overlap)}",
            )

    for field, value in (
        ("secrets", secrets),
        ("optional_secrets", optional_secrets),
        ("variables", variables),
    ):
        if value is None:
            continue
        for name in value:
            reason = forbidden_key_reason(name)
            if reason:
                report.error(
                    "forbidden-key-pattern",
                    f"{field} 登记了 v3.0 禁止键名 {name}：{reason}",
                )

    compat = manifest.get("compat", {})
    if not isinstance(compat, dict):
        report.warn("manifest-schema", "[compat] 必须是 table")
        compat = {}
    unknown_compat_sections = sorted(set(compat) - {"env_map", "expires_after"})
    if unknown_compat_sections:
        report.warn(
            "manifest-schema",
            f"[compat] 只支持 env_map 与 expires_after：{unknown_compat_sections}",
        )
    expires_after = compat.get("expires_after")
    if expires_after is not None and (not isinstance(expires_after, str) or not expires_after.strip()):
        report.warn("manifest-schema", "[compat] expires_after 必须是非空字符串")
    mapping = string_map(compat.get("env_map", {}))
    if mapping and sovereignty == "sovereign":
        report.error(
            "compat-sovereign-map",
            "sovereign 项目禁止使用 [compat.env_map]；只有 fork/port 可在过渡期映射上游键",
        )
    if mapping:
        remaining = "、".join(f"{source} -> {target}" for source, target in sorted(mapping.items()))
        expiry_note = (
            f"；expires_after={expires_after}"
            if isinstance(expires_after, str) and expires_after.strip()
            else ""
        )
        report.note("compat-env-map", f"仍存活的兼容映射：{remaining}{expiry_note}")
    if mapping is None:
        report.warn("manifest-schema", "[compat.env_map] 必须是标准键到上游键的字符串映射")
    elif secrets is not None and optional_secrets is not None and variables is not None:
        invalid_sources = sorted(name for name in mapping if not ENV_KEY.fullmatch(name))
        invalid_targets = sorted(name for name in mapping.values() if not ENV_KEY.fullmatch(name))
        if invalid_sources or invalid_targets:
            report.warn(
                "manifest-schema",
                f"[compat.env_map] 含非法键名：源 {invalid_sources}，目标 {invalid_targets}",
            )
        registered = set(secrets) | set(optional_secrets) | set(variables)
        unknown = sorted(set(mapping) - registered)
        if unknown:
            report.warn("manifest-schema", f"[compat.env_map] 只能映射已登记键：{unknown}")
        targets: dict[str, str] = {}
        duplicates: list[str] = []
        for source in sorted(registered):
            target = mapping.get(source, source)
            if target in targets and targets[target] != source:
                duplicates.append(f"{targets[target]}、{source} -> {target}")
            targets[target] = source
        if duplicates:
            report.warn("manifest-schema", f"[compat.env_map] 目标键重复：{duplicates}")

    seed_file = manifest.get("seed_file")
    other_objects = string_list(manifest.get("other_objects", []))
    if other_objects is None:
        report.warn("manifest-schema", "other_objects 必须是字符串数组")
    elif isinstance(seed_file, str) and seed_file and Path(seed_file).name not in other_objects:
        report.warn("other-object-unregistered", f"seed_file={seed_file} 未登记在 other_objects")

    for field in ("bucket_namespace", "dist_bucket", "mount_config_bucket"):
        value = manifest.get(field)
        if isinstance(value, str) and value and not SAFE_SLUG.fullmatch(value):
            report.warn("manifest-schema", f"{field} 不是安全的单段名称：{value!r}")
    for field in ("dist_bucket", "mount_config_bucket"):
        value = manifest.get(field)
        if isinstance(value, str) and DATE_IN_NAME.search(value):
            report.warn("bucket-no-date", f"{field}={value!r} 含日期；短期轮换项目请登记例外")

    for entry in malformed_deviations:
        report.warn("manifest-schema", f"deviations 条目必须是 '规则 id = 原因'：{entry}")


def resolve_from_ref(ref: str, build_args: dict[str, str]) -> tuple[str | None, str | None]:
    match = VARIABLE_REF.match(ref)
    if not match:
        return ref, None
    name = match.group(1) or match.group(2)
    return build_args.get(name), name


def image_name(ref: str) -> str:
    leaf = ref.rsplit("/", 1)[-1]
    return leaf.split("@", 1)[0].split(":", 1)[0].lower()


def has_explicit_image_version(ref: str) -> bool:
    leaf = ref.rsplit("/", 1)[-1]
    return "@" in leaf or ":" in leaf


def check_dockerfile(report: Report, root: Path) -> None:
    dockerfiles = [
        path
        for path in (root / "Dockerfile", root / "cloud" / "hfs" / "Dockerfile")
        if path.exists()
    ]
    if not dockerfiles:
        report.note("docker-review", "未找到 Dockerfile，跳过镜像静态检查")
        return

    for dockerfile in dockerfiles:
        build_args: dict[str, str] = {}
        aliases: set[str] = set()
        for line_number, line in enumerate(dockerfile.read_text(encoding="utf-8").splitlines(), start=1):
            arg_match = ARG_LINE.match(line)
            if arg_match and arg_match.group(2) is not None:
                build_args[arg_match.group(1)] = arg_match.group(2).strip()
                continue
            from_match = FROM_LINE.match(line)
            if not from_match:
                continue
            raw_ref, alias = from_match.group(1), from_match.group(2)
            resolved, variable = resolve_from_ref(raw_ref, build_args)
            if resolved is None:
                report.note(
                    "docker-review",
                    f"{dockerfile.name}:{line_number} FROM {raw_ref} 没有可静态解析的 ARG 默认值，需人工确认",
                )
                if alias:
                    aliases.add(alias.lower())
                continue
            if resolved.lower() in aliases:
                if alias:
                    aliases.add(alias.lower())
                continue

            display = f"{raw_ref}（默认 {resolved}）" if variable else resolved
            if image_name(resolved) not in BASE_IMAGES:
                report.warn(
                    "business-image",
                    f"{dockerfile.name}:{line_number} FROM {display} 疑似业务镜像；优先源码或成品车道",
                )
            elif not has_explicit_image_version(resolved):
                report.warn(
                    "base-image-version",
                    f"{dockerfile.name}:{line_number} base image {display} 未显式声明 latest、tag 或 digest",
                )
            elif resolved.endswith(":latest"):
                report.note("base-image-version", f"{dockerfile.name}:{line_number} 显式选择 base image latest")
            if alias:
                aliases.add(alias.lower())


def normalized_sensitive_key(key: str) -> bool:
    with_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    normalized = with_boundaries.lower().replace("-", "_").replace(".", "_")
    return any(normalized == term or normalized.endswith(f"_{term}") for term in SENSITIVE_KEY_SUFFIXES)


def placeholder_value(value: Any) -> bool:
    if value is None or value is False:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip().strip('"').strip("'")
    if not stripped or stripped.upper() in SAFE_PLACEHOLDERS:
        return True
    if re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}", stripped):
        return True
    if re.fullmatch(r"env:[A-Za-z_][A-Za-z0-9_]*", stripped):
        return True
    if ANGLE_PLACEHOLDER.fullmatch(stripped):
        return True
    return False


def embedded_credential(value: str) -> bool:
    """URL userinfo 密码、URL query 与分号 DSN 中的敏感字段实值；语义对齐同步器。"""
    for candidate in URL_VALUE.findall(value):
        candidate = candidate.rstrip(",);]")
        try:
            parsed = urllib.parse.urlsplit(candidate)
            password = parsed.password
        except ValueError:
            parsed = None
            password = None
        if password is not None and not placeholder_value(urllib.parse.unquote(password)):
            return True
        if parsed is not None:
            for key, query_value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            ):
                if normalized_sensitive_key(key) and not placeholder_value(query_value):
                    return True
    for match in DSN_FIELD.finditer(value):
        if normalized_sensitive_key(match.group("key")) and not placeholder_value(
            match.group("value")
        ):
            return True
    return False


def config_secret_leak(key_path: str, value: Any) -> bool:
    """判断 config.toml 中的值是否疑似真实机密；placeholder 和 ${ENV} 引用不算。"""
    if not isinstance(value, str) or not value:
        return False
    if placeholder_value(value):
        return False
    if SECRET_VALUE.search(value):
        return True
    if embedded_credential(value):
        return True
    leaf = key_path.rsplit(".", 1)[-1]
    return normalized_sensitive_key(leaf)


def iter_config_values(config: Any, prefix: tuple[str, ...] = ()) -> Any:
    if isinstance(config, dict):
        for key, value in config.items():
            yield from iter_config_values(value, (*prefix, key))
    elif isinstance(config, list):
        for item in config:
            yield from iter_config_values(item, prefix)
    else:
        yield ".".join(prefix), config


def check_config_schema(report: Report, root: Path, manifest: dict[str, Any]) -> None:
    """v3.0 固定基础 schema 校验。

    只有 manifest 显式声明 seed_file 才检查：声明即须存在（缺失 ERROR）；
    TOML 后缀另做 schema 校验；未声明 seed_file 的项目完全跳过。
    """
    if "seed_file" not in manifest:
        return
    seed_value = manifest.get("seed_file")
    if not isinstance(seed_value, str) or not seed_value:
        return
    relative = valid_relative_path(seed_value)
    if relative is None:
        return
    path = root.joinpath(*relative.parts)
    if not path.exists():
        report.error(
            "config-schema",
            f"已声明的 seed_file 不存在：{seed_value}；声明即须存在，否则移除声明",
        )
        return
    if PurePosixPath(seed_value).suffix != ".toml":
        report.note("config-schema", f"种子 {seed_value} 不是 TOML；schema 校验仅适用于 TOML 种子")
        return
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        report.error("config-schema", f"{seed_value} 解析失败：{exc}")
        return
    if not isinstance(config, dict):
        report.error("config-schema", f"{seed_value} 必须是 TOML table")
        return

    for section, required_keys in CONFIG_SCHEMA.items():
        value = config.get(section)
        if value is None:
            report.error("config-schema", f"{seed_value} 缺少必备节 [{section}]")
            continue
        if not isinstance(value, dict):
            report.error("config-schema", f"{seed_value} 的 [{section}] 必须是 table")
            continue
        for key in required_keys:
            if key not in value:
                report.error("config-schema", f"{seed_value} 缺少必备键 {section}.{key}")
        for key in sorted(set(value) - set(required_keys)):
            report.warn("config-schema", f"{seed_value} 未知键 {section}.{key}；确认它确有必要存在")
    for section in sorted(set(config) - set(CONFIG_SCHEMA) - CONFIG_OPTIONAL_SECTIONS):
        report.warn("config-schema", f"{seed_value} 未知节 [{section}]；确认它确有必要存在")

    for key_path, value in iter_config_values(config):
        if config_secret_leak(key_path, value):
            report.error(
                "config-schema",
                f"{seed_value} 的 {key_path} 疑似真实机密值；机密只能放 .env，config.toml 用 ${{ENV_NAME}} 引用",
            )


LEGACY_ALIAS_KEY = re.compile(r"^(?:ADMIN_TOKEN|.+_ADMIN_TOKEN)$")


def legacy_audit(root: Path, manifest_path: Path, manifest: dict[str, Any]) -> int:
    """旧标准（2.1/2.2）项目的只读迁移差距审计；不修改任何文件，退出码 2。"""
    standard = str(manifest.get("standard", ""))
    try:
        display_path = manifest_path.relative_to(root)
    except ValueError:
        display_path = manifest_path
    print("== 旧标准差距审计（只读，不修改任何文件）==")
    print(f"manifest：{display_path}，standard = {standard!r}")
    print('v3.0 正常运行只接受 standard = "3.0"；init/info/diff/push/pull 对旧标准一律拒绝。')
    print()

    declared: set[str] = set()
    for field in ("secrets", "optional_secrets", "variables", "local_only"):
        values = string_list(manifest.get(field, []))
        if values:
            declared.update(values)

    env_relative = valid_env_file(manifest.get("env_file"))
    env_path = root.joinpath(*env_relative.parts) if env_relative is not None else None
    env_keys: set[str] = set()
    env_file_readable = env_path is not None and env_path.is_file() and not env_path.is_symlink()
    if env_file_readable:
        env_keys = env_key_names(env_path)

    items: list[str] = []
    items.append("standard 改为 \"3.0\"")

    secret_files = string_list(manifest.get("secret_files", []))
    if secret_files:
        items.append(
            "移除 secret_files（已在 v3.0 取消）："
            f"{secret_files}；机密只登记 .env，原生结构化文件由 wrapper 从标准 .env 生成到 local/generated/"
        )

    top_env_map = manifest.get("env_map")
    if isinstance(top_env_map, dict) and top_env_map:
        sovereignty = manifest.get("sovereignty")
        if sovereignty == "sovereign":
            items.append(
                f"删除顶层 env_map：{sorted(top_env_map)}；sovereign 项目禁止映射，改用标准键名"
            )
        else:
            items.append(
                f"顶层 env_map 移入 [compat.env_map]：{sorted(top_env_map)}；仅 fork/port 可在过渡期使用"
            )

    forbidden_declared = sorted(name for name in declared if forbidden_key_reason(name))
    for name in forbidden_declared:
        items.append(f"manifest 登记的旧式键名改名：{name}（{forbidden_key_reason(name)}）")

    if env_relative is not None:
        if env_file_readable:
            forbidden_env = sorted(name for name in env_keys if forbidden_key_reason(name))
            if forbidden_env:
                items.append(
                    f"{env_relative} 中的旧式键名改名并迁移到标准键：{forbidden_env}（只列键名，不显示值）"
                )
        else:
            items.append(f"未找到可读的 {env_relative}；迁移时记得盘点其中的键")

    print("发现的差距：")
    for index, item in enumerate(items, start=1):
        print(f"  {index}. {item}")

    print()
    print("安全红线（不受标准版本豁免，只读检查）：")
    redline_found = False
    if env_relative is not None:
        git_ok = git_available(root)
        if not git_ok:
            print("  NOTE：当前目录不是 Git 工作树，无法执行 tracked/ignore 检查")
        else:
            if git_tracked(root, env_path):
                print(f"  ERROR [secret-in-git] {env_relative} 已被 Git 跟踪（密码、密钥不得进入 Git）")
                redline_found = True
            if not git_ignored(root, str(env_relative)):
                print(f"  WARN  [local-ledger-ignore] {env_relative} 未被 Git ignore，容易被误提交")
        if has_symlink_component(root, env_relative):
            print(f"  ERROR [local-plaintext-source] {env_relative} 包含 symlink")
            redline_found = True
        elif env_path.exists():
            if not env_path.is_file():
                print(f"  ERROR [local-plaintext-source] {env_relative} 必须是普通文件")
                redline_found = True
            else:
                mode = stat.S_IMODE(env_path.stat().st_mode)
                if mode != 0o600:
                    print(
                        f"  ERROR [local-plaintext-source] {env_relative} 权限必须是 0600，当前为 {mode:04o}"
                    )
                    redline_found = True
    if not redline_found:
        print("  未发现问题")

    print()
    print("旧对象盘点（需人工确认，只列路径与键名）：")
    inventory_found = False
    legacy_files: list[str] = []
    for pattern in ("*.secrets.toml", "*credentials*.yaml", "*credentials*.yml", "*credentials*.json"):
        legacy_files.extend(
            str(candidate.relative_to(root))
            for candidate in root.glob(pattern)
            if candidate.is_file() and not candidate.is_symlink()
        )
    legacy_files.extend(
        candidate.name
        for candidate in root.glob(".env.*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and not candidate.name.endswith((".example", ".sample", ".template"))
    )
    credentials_dir = root / "local" / "credentials"
    if credentials_dir.is_dir():
        legacy_files.extend(
            str(candidate.relative_to(root))
            for candidate in sorted(credentials_dir.rglob("*"))
            if candidate.is_file() and not candidate.is_symlink()
        )
    for entry in sorted(set(legacy_files)):
        print(f"  旧文件：{entry}")
        inventory_found = True
    for name in sorted(name for name in (declared | env_keys) if LEGACY_ALIAS_KEY.fullmatch(name)):
        print(f"  旧别名（需人工映射确认）：{name}")
        inventory_found = True
    if not inventory_found:
        print("  未发现")

    print()
    print("手动迁移步骤：")
    print("  1. 备份当前 .env、config.toml、hfs-dev.toml（例如复制到 local/）")
    print("  2. 按 README「从 2.1/2.2 迁移」键映射表改名，合并到标准四文件")
    print('  3. standard 改为 "3.0"，删除 secret_files；顶层 env_map 按主权处理（sovereign 删除，fork/port 迁入 [compat.env_map]）')
    print("  4. 重新运行 hfs-dev check 直至通过")
    return 2


def resolve_manifest_arg(root: Path, manifest_file: Path) -> tuple[Path | None, str | None]:
    """显式 --manifest 解析：必须位于项目根内；默认值保留 cloud/hfs/ 回退发现。"""
    relative = PurePosixPath(str(manifest_file))
    if relative.is_absolute() or ".." in relative.parts:
        return None, f"--manifest 必须是项目根内的相对路径：{manifest_file}"
    candidate = root.joinpath(*relative.parts)
    if candidate.is_file():
        return candidate, None
    if relative == PurePosixPath("hfs-dev.toml"):
        return find_manifest(root)
    return None, f"manifest 不存在：{manifest_file}"


def check_root(
    root: Path,
    *,
    require_local_values: bool = False,
    manifest_file: Path | None = None,
) -> int:
    if not root.is_dir():
        print(f"ERROR [input] 项目根不存在：{root}")
        return 2
    if manifest_file is None:
        manifest_path, location_note = find_manifest(root)
    else:
        manifest_path, location_note = resolve_manifest_arg(root, manifest_file)
        if manifest_path is None:
            print(f"ERROR [input] {location_note}")
            return 2
    manifest, raw, parse_error = parse_manifest(manifest_path)
    if parse_error is None and str(manifest.get("standard", "")) in LEGACY_STANDARDS:
        return legacy_audit(root, manifest_path, manifest)
    deviations, malformed = parse_deviations(manifest)
    report = Report(deviations)
    check_git_hygiene(
        report,
        root,
        manifest,
        require_local_values=require_local_values,
    )
    check_manifest(report, manifest_path, location_note, manifest, raw, parse_error, malformed)
    if parse_error is None:
        check_config_schema(report, root, manifest)
    check_dockerfile(report, root)
    report.note("manual-review", "仍需人工确认：Space 无闭源源码；拉取、配置和启动路径均 fail-closed")
    print(f"-- {report.errors} ERROR / {report.warnings} WARN")
    return 1 if report.errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="*", default=["."], help="项目根目录（默认当前目录）")
    parser.add_argument(
        "--require-local-values",
        action="store_true",
        help="要求 manifest 声明的本地明文事实源存在；本机验收使用，CI checkout 通常不使用",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="显式指定 manifest（相对项目根，如 hfs-dev.prod.toml）；默认自动发现",
    )
    args = parser.parse_args()
    result = 0
    for root_value in args.roots:
        root = Path(root_value).resolve()
        if len(args.roots) > 1:
            print(f"== {root}")
        result = max(
            result,
            check_root(
                root,
                require_local_values=args.require_local_values,
                manifest_file=args.manifest,
            ),
        )
    return result


if __name__ == "__main__":
    sys.exit(main())
