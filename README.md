# Hermes DashScope Image Gen

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

DashScope Qwen-Image 原生图片生成后端插件，为 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 提供阿里云百炼（DashScope）的 Qwen-Image 系列模型直接调用能力。

## 支持的模型

| 模型 | 说明 | 速度 |
|------|------|------|
| `qwen-image-2.0-pro` | 最高质量，复杂文字渲染，支持 1-6 张并发生成 | ~15s |
| `qwen-image-2.0` | 加速版，质量与速度均衡 | ~10s |
| `qwen-image-max` | 最高真实感，AI痕迹最少 | ~20s |
| `qwen-image-plus` | 多样艺术风格 | ~12s |

## 安装

### 方式一：pip 安装

```bash
pip install git+https://github.com/fingxing/hermes-dashscope-image-gen.git
```

### 方式二：手动安装

```bash
git clone https://github.com/fingxing/hermes-dashscope-image-gen.git
cd hermes-dashscope-image-gen
pip install -e .
```

然后启用插件：

```bash
hermes plugins enable image_gen/dashscope
```

### 方式三：直接复制（不用安装）

将 `hermes_dashscope_image_gen/` 目录下的 `plugin.yaml` 和 `__init__.py` 复制到：

```
~/.hermes/plugins/image_gen/dashscope/
```

然后启用：

```bash
hermes plugins enable image_gen/dashscope
```

## 配置

### 1. 设置 API Key

在 `~/.hermes/.env` 中添加：

```bash
DASHSCOPE_API_KEY=sk-your-api-key
```

获取 API Key：https://bailian.console.aliyun.com/?apiKey=1

### 2. 配置 image_gen

在 `~/.hermes/config.yaml` 中：

```yaml
image_gen:
  provider: dashscope
  model: qwen-image-2.0-pro
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1

plugins:
  enabled:
    - image_gen/dashscope
```

> **注意**：`base_url` 填写的是 DashScope 兼容模式地址（用于 LLM 对话），插件内部会自动转换为原生图片 API 端点 `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`。

### 3. 国际版用户

如果使用的是 DashScope 国际版，设置环境变量：

```bash
export DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
```

## 使用

配置完成后，直接在 Hermes 中使用 `image_generate` 工具即可：

```
生成一张蓝天白云的风景图，aspect_ratio=landscape
```

也可以通过 CLI 快速测试：

```bash
hermes chat -q "用image_generate生成一只猫" --yolo -t image_gen
```

生成的图片保存在 `~/.hermes/cache/images/`。

## 项目结构

```
hermes-dashscope-image-gen/
├── hermes_dashscope_image_gen/
│   ├── __init__.py        # 核心实现 (~450 行)
│   └── plugin.yaml        # 插件元数据
├── pyproject.toml
├── LICENSE
└── README.md
```

## 原理

Hermes 的图片生成采用插件化架构，所有后端通过 `ImageGenProvider` 抽象基类实现。

本插件实现要点：

1. **端点自动适配** — 从用户配置的兼容模式地址自动剥离 `/compatible-mode/v1` 后缀，拼接原生图片 API 路径
2. **原生 API 调用** — 使用 DashScope 原生 `multimodal-generation` 接口（非 OpenAI 兼容格式）
3. **尺寸映射** — 根据模型系列（qwen2 vs max/plus）自动选择正确的像素规格
4. **图片缓存** — DashScope 返回的 URL 24小时过期，自动下载缓存到本地

详见同级目录下的 `dashscope-qwen-image-plugin.md`（在同仓库的父项目中）。

## License

MIT
