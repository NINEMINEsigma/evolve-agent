# Third-Party Notice — ripgrep

本目录包含 Evolve Agent Windows x64 高性能搜索路径使用的 `ripgrep` 预编译可执行文件。

## Package

- Name: ripgrep
- Version: 15.2.0
- Platform: Windows x64 (`x86_64-pc-windows-msvc`)
- Included file: `rg.exe`
- Upstream repository: https://github.com/BurntSushi/ripgrep
- Release page: https://github.com/BurntSushi/ripgrep/releases/tag/15.2.0
- Source archive: `ripgrep-15.2.0-x86_64-pc-windows-msvc.zip`
- Source archive SHA-256: `71b2fef860abe467217a538ff31de02f5258807c0129f771846f87bd029aafc5`
- Included `rg.exe` SHA-256: `14231169855ec5205cf5a1b6f1db358ff4aed4247c86b69ce8aae647c77f6680`

## License

`ripgrep` is dual-licensed under MIT or UNLICENSE according to the upstream project. See the upstream repository for the full license texts and current notices.

## Usage in Evolve Agent

`origin_agent/system/search_engine.py` resolves this binary at runtime through `system.pathutils.get_agent_dir()`, so the same relative path works after `run.py` copies `origin_agent/` into the fast仓库 or fallback仓库 runtime copy.

If this binary is missing, blocked, corrupted, or fails its SHA-256 check, `SearchFiles` and `Grep` automatically fall back to the Python search engine and return `engine="python"` with a `warning` field.

## Upgrade procedure

1. Download the new official Windows x64 release archive from the upstream ripgrep release page.
2. Verify the archive SHA-256 against the upstream `.sha256` file.
3. Replace `rg.exe` in this directory with the archive's `rg.exe`.
4. Compute the new `rg.exe` SHA-256.
5. Update `SEARCH_RIPGREP_VERSION`, `SEARCH_RIPGREP_WINDOWS_X64_ARCHIVE_SHA256`, and `SEARCH_RIPGREP_EXE_SHA256` in `origin_agent/entity/constant.py`.
6. Update this notice file with the new version, archive name, archive SHA-256, and executable SHA-256.
