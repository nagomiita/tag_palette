# Tag Palette

## 環境構築

```bash
cd app
uv sync
python -m ensurepip
```

## ビルド方法

```bash
uv run nuitka --onefile --enable-plugin=tk-inter --standalone main.py
```

```mermaid
erDiagram
    images ||--o{ image_tags : has
    images ||--o{ poses : has
    tags ||--o{ image_tags : has
    tags ||--o{ tag_translations : has
    tags }o--|| categories : belongs_to
    tags ||--o{ tag_genres : has
    genres ||--o{ tag_genres : has

    images {
        int id PK
        string image_path
        string thumbnail_path
        text tag_embedding
        datetime created_at
        datetime registered_at
        boolean is_favorite
        boolean is_sensitive
        int view_count
    }

    image_tags {
        int id PK
        int image_id FK
        int tag_id FK
        float confidence
        string model_name
    }

    poses {
        int id PK
        int image_id FK
        blob embedding
        boolean is_flipped
    }

    tags {
        int id PK
        string name
        int category_id FK
        text embedding
        datetime registered_at
        boolean is_sensitive
        boolean disable
    }

    tag_translations {
        int id PK
        int tag_id FK
        string language
        string translated_name
        text note
    }

    categories {
        int id PK
        string name
    }

    genres {
        string id PK
        string name
        text note
    }

    tag_genres {
        int id PK
        int tag_id FK
        string genre_id FK
    }


```

```
robocopy app\images Z:\backup\images /MIR /SL /Z /W:5 /R:3 /LOG:backup.log
```
