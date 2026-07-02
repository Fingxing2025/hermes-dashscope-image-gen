# Hermes DashScope Image Gen

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Hermes Plugin](https://img.shields.io/badge/Hermes-Plugin-7c3aed.svg)](https://github.com/NousResearch/hermes-agent)

为 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 提供的阿里云百炼（DashScope）Qwen-Image 原生图片生成后端插件。

直接调用通义万相模型，无需经过 FAL.ai 等中间平台。

## 为什么需要这个插件？

Hermes 内置的生图后端只有 FAL.ai、OpenAI DALL-E、xAI、Krea，没有 DashScope。
Qwen-Image 系列模型在**中文文字排版**、复杂版面、多行文本渲染方面表现优异，
本插件让你能用已有的 DashScope API Key 直接调用。

## 支持的模型

| 模型 ID | 说明 | 速度 |
|----------|-------------|-------|
| `qwen-image-2.0-pro` | 最高质量，复杂文字渲染，支持 1–6 张并发生成。**（推荐）** | ~15s |
| `qwen-image-2.0` | 加速版，质量与速度均衡。 | ~10s |
| `qwen-image-max` | 最高真实感，AI 痕迹最少，画面自然。 | ~20s |
| `qwen-image-plus` | 多样艺术风格，文字渲染良好。 | ~12s |

## 安装

### 方式一：pip 安装

```bash
pip install git+https://github.com/Fingxing2025/hermes-dashscope-image-gen.git
```

### 方式二：克隆 + 可编辑安装

```bash
git clone https://github.com/Fingxing2025/hermes-dashscope-image-gen.git
cd hermes-dashscope-image-gen
pip install -e .
```

然后启用插件：

```bash
hermes plugins enable image_gen/dashscope
```

### 方式三：直接复制（无需安装）

将两个文件复制到 Hermes 插件目录：

```bash
mkdir -p ~/.hermes/plugins/image_gen/dashscope/
cp hermes_dashscope_image_gen/plugin.yaml ~/.hermes/plugins/image_gen/dashscope/
cp hermes_dashscope_image_gen/__init__.py ~/.hermes/plugins/image_gen/dashscope/
hermes plugins enable image_gen/dashscope
```

## 配置

### 1. 设置 API Key

在 `~/.hermes/.env` 中添加：

```bash
DASHSCOPE_API_KEY=sk-你的密钥
```

获取 Key：https://bailian.console.aliyun.com/?apiKey=1

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

> **注意：** `base_url` 填写的是 DashScope 兼容模式地址（也是 LLM 对话用的地址）。
> 插件内部会自动剥离 `/compatible-mode/v1` 后缀，拼接原生图片 API 路径
> `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`。

### 3. 国际版用户

如果使用的是 DashScope 国际版，通过环境变量覆盖：

```bash
export DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
```

## 使用

配置完成后，直接在 Hermes 中使用 `image_generate` 工具：

```
生成一张蓝天白云的风景图，写实摄影风格
```

CLI 快速测试：

```bash
hermes chat -q "生成一只坐在桌上的橘猫" --yolo -t image_gen
```

生成的图片保存在 `~/.hermes/cache/images/`。

## 原理

### 架构

Hermes 的图片生成采用插件化 `ImageGenProvider` 架构，每个后端实现一个子类：

```
plugins/image_gen/<name>/
├── plugin.yaml    # 元数据：名称、类型、需要的环境变量
└── __init__.py    # ImageGenProvider 子类 + register() 入口
```

### 端点解析（最容易踩坑的地方）

DashScope 有**两套独立的 API 路径**：

| 接口 | 路径 | 用途 |
|------|------|------|
| OpenAI 兼容 | `/compatible-mode/v1/chat/completions` | LLM 文本对话 |
| 原生 API | `/api/v1/services/aigc/multimodal-generation/generation` | 图片生成 |

用户配置的 `image_gen.base_url` 通常指向兼容模式地址（因为那也是 LLM 对话用的地址）。
插件会检测并剥离 `/compatible-mode/v1` 后缀，再拼接原生图片 API 路径：

```
用户配置:     https://dashscope.aliyuncs.com/compatible-mode/v1
                  ↓ 剥离 /compatible-mode/v1
             https://dashscope.aliyuncs.com
                  ↓ 拼接 /api/v1/services/aigc/multimodal-generation/generation
最终请求:     https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
```

### API 请求格式

DashScope 原生多模态生成接口使用与 OpenAI 图片 API 完全不同的请求格式：

```json
{
  "model": "qwen-image-2.0-pro",
  "input": {
    "messages": [{
      "role": "user",
      "content": [{ "text": "你的提示词" }]
    }]
  },
  "parameters": {
    "size": "2048*2048",
    "n": 1,
    "prompt_extend": true,
    "watermark": false
  }
}
```

注意：尺寸用 `*` 连接（如 `2048*2048`），不是 OpenAI 格式的 `x`。

### 响应与缓存

DashScope 返回的是**临时 URL**，24 小时后过期：

```json
{
  "output": {
    "choices": [{
      "message": {
        "content": [{ "image": "https://dashscope-result-sh.oss-.../xxx.png" }]
      }
    }]
  }
}
```

插件会在生成时立即下载图片并缓存到 `~/.hermes/cache/images/`，
确保文件在 URL 过期后仍然可用。

### 尺寸映射

不同模型系列支持不同的分辨率范围：

| 宽高比 | qwen-image-2.0-pro / 2.0 | qwen-image-max / plus |
|--------|--------------------------|----------------------|
| landscape (16:9) | 2688×1536 | 1664×928 |
| square (1:1) | 2048×2048 | 1328×1328 |
| portrait (9:16) | 1536×2688 | 928×1664 |

## 项目结构

```
hermes-dashscope-image-gen/
├── hermes_dashscope_image_gen/
│   ├── __init__.py        # ImageGenProvider 实现（~470 行，全英文注释）
│   └── plugin.yaml        # Hermes 插件元数据
├── pyproject.toml
├── LICENSE                # MIT
├── README.md              # English
└── README_zh.md           # 中文（本文件）
```

## 向 Hermes 主仓库贡献

本插件设计为可直接提交 PR 到 Hermes 主仓库。
贡献步骤：

1. Fork [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
2. 将 `hermes_dashscope_image_gen/` 复制到 `plugins/image_gen/dashscope/`
3. 以 `feat:` 类型提交 PR

## License

MIT — 详见 [LICENSE](LICENSE)。
