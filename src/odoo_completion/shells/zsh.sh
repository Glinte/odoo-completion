# Load after compinit. The helper never returns executable shell code.
_odoo_completion() {
    local kind value description
    local -a descriptions
    while IFS=$'\t' read -r kind value description; do
        [[ -n "$value" ]] || continue
        descriptions=("$description")
        case "$kind:$value" in
            directory:*|nospace:*|*:) compadd -U -S '' -d descriptions -- "$value" ;;
            *) compadd -U -d descriptions -- "$value" ;;
        esac
    done < <(ODOO_COMPLETION_HELPER _complete --shell zsh \
        --line "$BUFFER" --point "$CURSOR" --cwd "$PWD" 2>/dev/null)
}
compdef _odoo_completion odoo-bin ./odoo-bin
compdef -p _odoo_completion '*/odoo-bin'
