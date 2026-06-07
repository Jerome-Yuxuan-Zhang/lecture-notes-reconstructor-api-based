# 讲义重构工作台

这是一个面向普通用户的一键式讲义重构程序。用户选择课程材料文件夹，配置一个兼容 OpenAI 接口的模型 API，程序会生成：

- `lecture.html`
- `assets/` 图表文件夹
- `script4.../` 图表生成脚本文件夹
- `self_check.md` 覆盖核对
- `manifest.json`
- `source_index.json`
- `reference_hits.json`
- `run.log`
- 可分享的 `.zip` 输出包

## 一键启动

普通用户直接双击：

```text
start_app.bat
```

启动器会自动完成：

- 首次创建本地虚拟环境 `.venv`
- 首次安装依赖；之后只有 `requirements.txt` 变化时才更新依赖
- 打开浏览器
- 启动讲义重构工作台

浏览器地址：

```text
http://127.0.0.1:8080
```

使用期间不要关闭启动器窗口。关闭窗口或在窗口里按 `Ctrl+C`，程序就会停止。

## 基本使用流程

1. 双击 `start_app.bat`。
2. 在“配置”页点击“浏览”，选择“输入材料文件夹”和“输出根目录”。
3. 选择 API 提供商，例如 `Qwen`。
4. 选择常用模型，或在“模型名称”里手动填写模型名。
5. 填写 API Key，或提前配置环境变量。
6. 点击“测试 API”，确认连通。
7. 点击“保存配置”。如需保存密钥，勾选“记住 API Key（系统钥匙串）”。
8. 到“材料”页点击“扫描材料”。
9. 到“运行”页点击“开始生成”。
10. 生成完成后，在“历史输出”里查看输出文件夹和 zip 包。

## 主讲材料与参考资料

PPT、课堂讲义、作业题、Excel 等需要逐页覆盖的材料，直接放在模块文件夹里。整本教材或补充阅读不要和 PPT 混在同一层当主材料；建议放进 `references/`、`textbook/`、`books/`、`参考/`、`教材/` 这类文件夹，或在文件名里包含这些关键词。

程序会把这些文件标记为 `reference`：先全文抽取成本地可检索资料，但不会在大纲阶段把整本书塞进 API，也不会把它纳入逐页覆盖核对。生成正式讲义前，程序会根据 PPT 和大纲关键词在 reference 里检索相关片段，例如遇到 “investment banking” 时查找教材里的相关段落，再把命中的摘录喂给 API 做深入讲解。

每次输出包里会生成 `reference_hits.json`，记录本轮到底检索到了哪些参考片段。若这里为空，说明本轮没有找到足够相关的教材段落，讲义会主要依据主讲材料生成。

## 批量子文件夹模式

如果一次要处理多个模块，把材料整理成这样的结构：

```text
input/
├── module1/
│   ├── slides.pdf
│   └── notes.docx
├── module2/
│   ├── lecture.pptx
│   └── exercises.xlsx
└── module3/
    └── reading.pdf
```

操作方式：

1. 在“输入材料文件夹”里选择最外层的 `input` 文件夹。
2. 开启“批量子文件夹模式”。
3. 到“材料”页点击“扫描材料”，确认显示的是 `module1`、`module2` 等子文件夹。
4. 到“运行”页点击“开始生成”。

批量模式的规则：

- 只处理输入目录下的一级子文件夹。
- 按子文件夹名称的字母顺序处理。
- 每个子文件夹单独生成一套输出包。
- 每个子文件夹都会创建新的 API client，并重新发送独立消息，不会继承上一个模块的上下文或记忆。
- 输出项目名会自动变成 `项目名_子文件夹名`，方便区分。

## 以 Qwen API 为例

阿里云百炼官方文档说明，在 Chatbox 等工具里调用 Qwen 通常需要三项信息：

- API Key
- API Key 所属地域的 Base URL
- 模型名称，例如 `qwen-plus`

北京地域常用 Base URL：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

推荐步骤：

1. 打开阿里云百炼控制台。
2. 进入 API Key 页面。
3. 点击“创建 API Key”。
4. 选择默认业务空间，按需设置权限。
5. 创建后复制 API Key，并妥善保存。
6. 回到本软件，在“API 提供商”选择 `Qwen`。
7. 确认 Base URL 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
8. 选择或填写模型名，例如 `qwen-plus`、`qwen-turbo`、`qwen-vl-max`。
9. 粘贴 API Key，点击“测试 API”。

官方参考：

- 阿里云百炼获取 API Key：https://help.aliyun.com/zh/dashscope/opening-service
- 阿里云百炼 OpenAI 兼容接口说明：https://help.aliyun.com/zh/model-studio/developer-reference/get-api-key

## 支持的 API 提供商

软件内置了常见 OpenAI 兼容提供商预设：

- Qwen
- DeepSeek
- OpenAI
- OpenRouter
- SiliconFlow
- Moonshot
- Zhipu
- MiniMax
- Custom

每个预设都带常用模型下拉选项。模型更新很快，如果下拉里没有你要的模型，直接在“模型名称（可手动覆盖）”里输入即可。

## 自定义 API 提供商

如果你使用其他 OpenAI 兼容服务：

1. 在“API 提供商”选择 `Custom`，或任选一个接近的预设。
2. 填写 `Base URL`，例如 `https://example.com/v1`。
3. 填写“模型名称”。
4. 填写环境变量名，例如 `MY_PROVIDER_API_KEY`。
5. 如该模型支持图片 OCR，保持“视觉 OCR”开启；否则关闭。
6. 在“保存为自定义提供商名称”里输入名称。
7. 点击“保存为自定义”。
8. 点击“保存配置”。

以后打开软件时，这个自定义提供商会出现在下拉列表里。

## API Key 安全

API Key 很重要，不要上传到 GitHub。

本软件的默认策略：

- API Key 默认不保存到项目目录。
- 不会写入输出包。
- 不会写入 `manifest.json`。
- 不会写入 `settings.json`。
- 勾选“记住 API Key（系统钥匙串）”时，程序会尝试写入系统钥匙串。
- 非敏感配置保存在用户目录：`C:\Users\<你的用户名>\.lecture_reconstructor\settings.json`。

更安全的方式是使用环境变量。例如 PowerShell：

```powershell
$env:DASHSCOPE_API_KEY="你的 Qwen API Key"
```

然后启动软件即可。不要把 API Key 写进代码、README、截图或 GitHub Issue。

## 上传 GitHub 前检查

项目已经包含 `.gitignore`，会忽略：

- `.venv/`
- `outputs/`
- `.env`
- `.env.*`
- `*.key`
- `*.pem`
- `*.zip`
- `*.log`
- Python 缓存

上传前建议执行：

```powershell
git status --short
git add .
git status --short
```

确认没有 `.venv/`、`outputs/`、`.env`、zip、key 文件后再提交。

还可以扫一遍疑似密钥：

```powershell
rg -n -S -u "sk-[A-Za-z0-9]|DASHSCOPE_API_KEY\s*=|DEEPSEEK_API_KEY\s*=|Bearer\s+[A-Za-z0-9._-]{20,}" .
```

如果只看到代码里的字段名，例如 `API Key`，通常没问题；如果看到真实密钥值，必须先删除并重置密钥。

## 常见问题

### 每次打开都会重新安装依赖吗？

不会。`start_app.bat` 第一次会安装依赖，之后只有 `requirements.txt` 改变时才更新。

### Max output tokens 应该填多少？

默认是 `180000`。讲义很长时不要设太小。不同模型的真实上限不同，如果超过模型限制，API 会返回错误；把数值调低后重试即可。

### 扫描图片或扫描版 PDF 怎么办？

开启“视觉 OCR”。程序会把图片或扫描页交给所选模型识别。所选模型必须支持视觉输入，否则请关闭“视觉 OCR”或换视觉模型。

### 图表脚本 timed out after 60 seconds 是什么？

这是本地执行 `script4.../*.py` 图表脚本超时，不是讲义 API 本身报错。程序会限制每个图表脚本单次最多运行 60 秒，防止模型生成的代码卡在字体下载、无限循环、交互窗口或过慢布局里。

如果配置了“图表代码 API”，程序会把失败原因、stdout/stderr 和原脚本自动发回图表模型 debug，并重跑一次修复后的脚本。若重试仍失败，错误会写入 `run.log` 和 `manifest.json`，输出包仍会生成，方便手工检查对应脚本。

### 输出在哪里？

默认在项目的 `outputs/` 文件夹。每次生成都会新建一个时间戳文件夹，并额外生成 zip 包。
