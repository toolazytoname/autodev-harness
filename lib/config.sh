#!/bin/bash
# Collect API keys for project during plan phase

collect_api_keys() {
    local project_dir="$1"
    local keys_needed="$2"  # comma-separated: vercel,github,supabase

    echo "=== API Key Configuration ==="
    echo ""

    mkdir -p "$project_dir/.autodev-harness"

    local config_file="$project_dir/.autodev-harness/config.json"

    # Initialize or read existing
    if [[ -f "$config_file" ]]; then
        echo "Existing config found at: $config_file"
    else
        echo "Creating new config..."
    fi

    # Prompt for each key if needed
    IFS=,' read -ra NEEDED <<< "$keys_needed"
    for key in "${NEEDED[@]}"; do
        case "$key" in
            vercel)
                read -p "Vercel Token (VERCEL_TOKEN): " val
                [[ -n "$val" ]] && update_config "$config_file" "vercel_token" "$val"
                ;;
            github)
                read -p "GitHub Token (GITHUB_TOKEN): " val
                [[ -n "$val" ]] && update_config "$config_file" "github_token" "$val"
                ;;
            supabase)
                read -p "Supabase Key (SUPABASE_KEY): " val
                [[ -n "$val" ]] && update_config "$config_file" "supabase_key" "$val"
                ;;
        esac
    done

    # Create .gitignore for the project
    cat > "$project_dir/.autodev-harness/.gitignore" <<EOF
# API Keys and Secrets
.env
*.key
config.json
.secrets

# Dependencies
node_modules/

# Build outputs
dist/
build/

# IDE
.idea/
.vscode/

# OS
.DS_Store
Thumbs.db
EOF
    echo ""
    echo "Created .autodev-harness/.gitignore"
}

update_config() {
    local file="$1"; local key="$2"; local val="$3"
    if grep -q "\"$key\"" "$file" 2>/dev/null; then
        sed -i  "s/\"$key\": \"[^\"]*\"/\"$key\": \"$val\"/" "$file"
    else
        echo "  \"$key\": \"$val\"," >> "$file"
    fi
}

detect_required_keys() {
    local brief="$1"
    local research="$2"
    local keys=""

    # Detect from brief and research
    grep -i "vercel" "$brief" "$research" 2>/dev/null && keys="${keys:+$keys,}vercel"
    grep -i "github" "$brief" "$research" 2>/dev/null && keys="${keys:+$keys,}github"
    grep -i "supabase" "$brief" "$research" 2>/dev/null && keys="${keys:+$keys,}supabase"

    echo "$keys"
}
