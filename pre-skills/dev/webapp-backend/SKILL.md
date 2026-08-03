---
name: webapp-backend
description: 为前端 Web 项目嫁接后端——API、数据库、认证（tRPC + Drizzle ORM + Hono + MySQL + OAuth 2.0 端到端类型安全）。当用户需要给 Web 应用加后端、REST/API、数据库、登录认证、用户系统、持久化存储时使用。源自通用智能体工具包（Universal Agent Toolkit）。
category: dev
version: 1.0.0-ea
author: "Eve (Evolve Agent 本地化)"
tags:
  - backend
  - api
  - database
  - auth
  - fullstack
---

> **Evolve Agent 本地化注记**
>
> 本技能源自通用智能体工具包（Universal Agent Toolkit），由 Eve（Evolve Agent）本地化接入，转为本地系统专用。
>
> - **前置**：通常配合 `ui/frontend-design`（含 `references/toolkit-webapp-frontend.md` 工程实现指南）使用
> - **技术栈**：tRPC + Drizzle ORM + Hono + MySQL + OAuth 2.0；需要安装依赖时用 `install_package` 或 `run_command`
> - **平台注意**：文中 `lsof -ti:<port> | xargs kill` 为 Unix 命令，Windows 下用 `netstat -ano | findstr :<port>` + `taskkill /PID <pid> /F`
> - **数据库**：本系统环境需自备 MySQL；生产迁移用 `db:generate` + `db:migrate`
> - **诚实边界**：宿主平台内置登录/云数据库时优先用平台能力；自部署副本需要自己的认证和数据库

# Web 后端构建（通用版）

> 对应能力：为已有前端项目嫁接后端——API、数据库、认证；增量式安装能力。

## 技术栈

tRPC + Drizzle ORM + Hono + MySQL + OAuth 2.0（端到端类型安全）。后端作为增量层**嫁接**到前端项目上：新增 `api/`、`contracts/`、可选 `db/`——**绝不替换或修改已有前端文件**。

**前提**：已有前端项目（见 `webapp-frontend.md`）。

## 能力分级（增量安装）

| 能力 | 提供 | 依赖 |
|------|------|------|
| `db` | Drizzle ORM + 数据库——`db/`、连接配置、迁移 | — |
| `auth` | OAuth 登录 + 用户管理——登录页、useAuth、鉴权布局 | 需要 `db`（自动带上） |

基础设施（Hono 服务器、tRPC、contracts）首次安装时自动就位。

## 工作流

**前端先行**（UI 已成型）：前端初始化并开发页面 → 嫁接后端（自动接好 provider 与路由）→ `npm run check` 验证 → 加 tRPC 路由、数据表、把前端接到 API。

**从零全栈**：前端初始化后立即嫁接后端 → 类型检查 → 前后端并行开发。

**数据库**：开发期用 `db:push` 同步 schema；生产用 `db:generate` 生成迁移 SQL + `db:migrate` 应用。

## 常见错误（务必规避）

- **不要手写数据库实体的 TS 接口**——用 `typeof table.$inferSelect` 保持与序列化层（如 superjson 的 Date 序列化）类型对齐；手写 `createdAt: string` 会与实际 `Date` 对象冲突。
- **不要写裸 SQL**——一律用 ORM 的类型安全查询 API。
- **不要改框架内部目录**（鉴权、静态服务等生成的基础设施）——在其上构建，不在其中构建。
- **前端不要直接 import `api/`**——前后端共享类型/常量走 `contracts/` 层。
- **tRPC 输入不要跳过 Zod 校验**——mutation 和带参查询都要 `.input(z.object({...}))`。
- **外键类型匹配**：自增主键是 `bigint unsigned`，外键列必须用相同的 `bigint` 无符号类型；MySQL 每表只允许一个自增列，外键不能再用自增。
- **绝不靠 drop 表修复失败迁移**——库中可能有用户数据。改对 schema 后用 introspect 式同步恢复；绝不使用自动接受破坏性变更的强制推送。
- **绝不改动生成的 `.env` 凭据**——其中的 key、URL、secret、连接串都是预配好可直接用的。
- **不要改默认端口**。

## 排障速查

- **端口占用**（Windows）：`netstat -ano | findstr :<port>` → `taskkill /PID <pid> /F`。
- **数据库连接被拒**：核对 `.env` 的连接串、数据库是否在跑、是否已执行 schema 同步。
- **OAuth 回调失败**：回调地址必须是 `{origin}/api/oauth/callback`，核对平台应用配置与环境变量一致。
- **迁移失败**：MySQL 不支持事务性 DDL，失败可能留下半完成状态——修 schema → introspect 同步 → 删除坏迁移文件及其 journal 记录 → 重新生成干净基线迁移。
- **加了路由报类型错**：确认路由已注册进根 router——`AppRouter` 类型从根路由派生并自动传导到前端。

## 诚实边界

- 宿主平台若内置登录（平台 OAuth）和云数据库，就用平台能力，不要去搜"怎么接 XX 登录"。
- 代码可导出，但平台登录与平台数据库不随导出代码走——自部署副本需要自己的认证和数据库，对用户说明这一点。
- 明确能力边界（如第三方支付、第三方 OAuth、复杂外部 SaaS 集成是否支持），不硬撑、不造假。
