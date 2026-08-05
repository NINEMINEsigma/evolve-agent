---
name: ssh-remote
description: "SSH 远程操作指南。通过 run_command 工具直接调用系统原生 ssh/scp 命令，在远程服务器上执行命令、上传和下载文件。适用于远程服务器管理、部署、日志收集等场景。"
version: 1.0.0
author: Hermes Agent
category: dev
tags:
  - ssh
  - scp
  - remote
  - shell
  - transfer
  - deploy
---

# ssh-remote

SSH 远程操作指南。所有命令通过 `run_command` 工具直接执行，不使用 Python 脚本间接调用。

## 使用方式

通过 `run_command` 工具直接执行 `ssh`/`scp` 命令。`run_command` 为 dangerous 级工具，每次调用会触发审批流程。

所有命令共享以下安全 flag：

```
-o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10
```

- `StrictHostKeyChecking=accept-new`：首次连接新主机自动接受 host key；密钥变更时拒绝连接
- `BatchMode=yes`：禁止交互式密码提示，避免挂死
- `ConnectTimeout=10`：连接阶段超时 10 秒

## 前置条件

- 系统已安装 OpenSSH 客户端（ssh / scp）
- 目标主机格式为 `user@host`（如 `root@10.0.0.1`）
- 已配置 SSH 密钥或 `~/.ssh/config`（禁止交互式密码输入）

## 执行远程命令

```bash
ssh -p <port> -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 <user@host> "<command>"
```

示例：

```bash
ssh -p 22 -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 root@10.0.0.1 "ls -la /var/log"
```

## 上传文件 (scp)

```bash
scp -P <port> -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 [-r] <local_path> <user@host>:<remote_path>
```

示例：

```bash
scp -P 22 -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 config.yml root@10.0.0.1:/etc/app/config.yml
```

`-r` 递归上传目录。

## 下载文件 (scp)

```bash
scp -P <port> -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 [-r] <user@host>:<remote_path> <local_path>
```

示例：

```bash
scp -P 22 -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10 root@10.0.0.1:/var/log/app.log ./app.log
```

## 注意事项

- 端口 flag 不同：`ssh` 用 `-p`（小写），`scp` 用 `-P`（大写）
- 远程命令可能对服务器造成直接影响，调用前应向用户说明原因
- scp 会覆盖目标路径的同名文件
- 本地路径如果是沙箱逻辑路径（`ws:`/`fork:` 前缀），`run_command` 会自动展开为真实绝对路径