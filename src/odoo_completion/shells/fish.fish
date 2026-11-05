function __odoo_completion
    set -l line (commandline -cp)
    ODOO_COMPLETION_HELPER _complete --shell fish \
        --line "$line" --point (string length -- "$line") --cwd "$PWD" 2>/dev/null
end
complete -c odoo-bin -f -a '(__odoo_completion)'
