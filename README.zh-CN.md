# judge-repo

[English](README.md) | **简体中文**

> Star 衡量的是关注度。`judge-repo` 在你依赖一个 GitHub 项目前评估它的健康信号：是否还在维护、是否响应用户、是否依赖单一维护者、是否有人在用。
>
> **预览版：** 阈值尚未校准，分数与开发者满意度的一致性也未经证实。请把分数作为决策的参考之一。

[![CI](https://github.com/zenHeart/judge-repo/actions/workflows/ci.yml/badge.svg)](https://github.com/zenHeart/judge-repo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-6f42c1.svg)](https://agentskills.io)

## 安装

需要 Python 3.9+ 和 [GitHub CLI](https://cli.github.com)，并已执行 `gh auth login`。

```bash
npx skills add zenHeart/judge-repo -g
```

支持 Claude Code、Codex、Cursor 等兼容 [Agent Skills](https://agentskills.io) 的工具。去掉 `-g` 则只安装到当前项目。

<details>
<summary>Claude Code 插件</summary>

```text
/plugin marketplace add zenHeart/judge-repo
/plugin install judge-repo
```

插件技能带命名空间，调用命令为 `/judge-repo:judge-repo`。
</details>

<details>
<summary>手动安装</summary>

```bash
git clone https://github.com/zenHeart/judge-repo
mkdir -p ~/.claude/skills
cp -R judge-repo/skills/judge-repo ~/.claude/skills/
```
</details>

## 使用

```text
/judge-repo moment/moment
```

```text
moment/moment: 65/100 · C · Review before depending (confidence 100%)

| Dimension              | Score | Max |
|------------------------|------:|----:|
| Maintenance activity   |  17.7 |  25 |
| Responsiveness         |   9.8 |  25 |
| Contributor resilience |   8.5 |  15 |
| Engineering            |  18.1 |  20 |
| Real adoption          |  14.1 |  15 |

Capped at 65: README declares maintenance mode
```

| 命令 | 作用 |
|---|---|
| `/judge-repo owner/repo` | 给单个仓库打分 |
| `/judge-repo a/b c/d e/f` | 对比多个仓库，按分数排序 |
| `/judge-repo search "http client" --language go` | 查找候选，并按分数和需求相关性排序 |
| `/judge-repo feedback <内容>` | 生成 Issue 草稿，确认后提交 |
| `/judge-repo doctor` | 检查 `gh`、登录状态和 API 配额 |
| `/judge-repo version` | 查看版本 |

也可以直接用自然语言提问，例如“这个仓库靠谱吗？”“想学构建工具该看哪些仓库？”

脚本可以脱离 Agent 独立运行，加 `--format json` 可得到结构化输出：

```bash
python3 skills/judge-repo/scripts/judge.py vitejs/vite --format json
```

## 评分方式

| 维度 | 分值 | 信号 |
|---|---:|---|
| 维护活性 | 25 | 最近推送、年提交量、发版频率 |
| 响应治理 | 25 | 维护者响应率与时长、外部 PR 合并、代码评审 |
| 贡献者韧性 | 15 | 巴士因子、活跃作者数 |
| 工程质量 | 20 | 许可证、CI、测试、OpenSSF Scorecard |
| 真实采用 | 15 | 包下载量；没有包时用依赖方或发布下载量 |

- **同样的数据得到同样的分数**：所有数字都由脚本计算，Agent 只判断 README 的状态文字是否确实声明项目已进入维护模式或废弃。
- **总分不随意图变化**：说明需求后，结果按“总分 × 相关性”排序，并显示每个仓库的相关理由。
- **封顶规则优先于指标**：已归档、长期无提交、无许可证、已废弃、存在已知漏洞或自称维护模式的项目都有分数上限。
- **缺失数据如实标注**：每个结果都带置信度，置信度低时给出分数区间。
- **内容仓不给总分**：清单、提示词合集没有测试和依赖方可供衡量。

完整模型见 [references/model.md](skills/judge-repo/references/model.md)。

## 局限

- 分数衡量的是项目健康度，不评审代码正确性，也不判断是否适合你的场景。
- 无法证明刷星。GitHub 在 2026 年把 stargazer 身份数据限制为仅仓库管理员和协作者可读，目前只能观察增长形态。
- 只有 npm 或 PyPI 数据显示使用广泛、未废弃且最新版无已知漏洞时，已完成的库才不会因提交和发版少而失分。
- 阈值只是初始校准，尚未用人工标注的基准集验证。如果你不同意某个分数，欢迎运行 `/judge-repo feedback`。

## 数据与隐私

- GitHub 请求使用你现有的 `gh` 登录状态，judge-repo 不读取也不保存 token。
- 被评估的仓库名和包名还会发送给 `api.securityscorecards.dev`、GitHub 公开的 dependents 页面、`registry.npmjs.org`、`api.npmjs.org`、`pypi.org`、`pypistats.org` 和 `api.osv.dev`。
- `feedback` 只有在你确认草稿后才会提交。它会替换本机 home 路径、拒绝疑似凭据的内容，并附上工具、`gh`、Python 和操作系统的版本。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题请按 [SECURITY.md](SECURITY.md) 报告。

## 许可证

[MIT](LICENSE)
