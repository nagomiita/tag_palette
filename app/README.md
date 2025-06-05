# Tag Palette

## 環境構築

```bash
cd app
uv sync
```

## ビルド方法

```bash
uv run nuitka --onefile --enable-plugin=tk-inter --standalone main.py
```
