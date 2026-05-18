#!/usr/bin/env bash
# claude-all installer
# Interactive menu to select and install agents/skills/plugins/mcps
# at user level (~/.claude/) or project level (./.claude/)
#
# Usage:
#   ./install.sh                    # Show full interactive menu
#   ./install.sh coding             # Filter to 'coding' category
#   ./install.sh coding aws         # Filter to coding/agents/aws
#   ./install.sh --help             # Show help

set -euo pipefail

# --- Configuration ---
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_CLAUDE_DIR="$HOME/.claude"
PROJECT_CLAUDE_DIR="$(pwd)/.claude"

# --- Colors ---
if [[ -t 1 ]]; then
  RED=$'\e[31m'
  GREEN=$'\e[32m'
  YELLOW=$'\e[33m'
  BLUE=$'\e[34m'
  CYAN=$'\e[36m'
  BOLD=$'\e[1m'
  DIM=$'\e[2m'
  RESET=$'\e[0m'
else
  RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' DIM='' RESET=''
fi

# --- Helpers ---
print_header() {
  echo
  echo "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${RESET}"
  echo "${BOLD}${CYAN}║              claude-all installer                            ║${RESET}"
  echo "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo
}

print_help() {
  cat <<EOF
${BOLD}claude-all installer${RESET}

${BOLD}Usage:${RESET}
  ./install.sh                Show full interactive menu
  ./install.sh <filter>...    Filter items (e.g. './install.sh coding aws')
  ./install.sh --help         Show this help
  ./install.sh --list         List all available items (no install)

${BOLD}Filters:${RESET}
  coding              All coding-related items
  coding agents       All agents
  coding agents aws   Only AWS agents
  coding skills       All skills
  ...

${BOLD}Installation level:${RESET}
  Chosen interactively after item selection.
  - User:    ~/.claude/   (available everywhere)
  - Project: ./.claude/   (current directory only)

${BOLD}Installation method:${RESET}
  Symlinks (so edits in the repo propagate everywhere).
EOF
}

# --- Discover items ---
# Output format: <type>|<category>|<subcategory>|<name>|<path>
discover_items() {
  local filter_args=("$@")

  # Find all .md files (agents, skills) and directories (plugins, mcps)
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    # Path relative to repo root
    local rel="${path#$REPO_ROOT/}"

    # Parse: coding/agents/aws/cloudwatch-inspector.md
    # or:    coding/skills/python/brunofaust-python-style/SKILL.md
    IFS='/' read -ra parts <<< "$rel"

    local category="${parts[0]:-}"        # coding
    local kind="${parts[1]:-}"            # agents|skills|plugins|mcps
    local subcategory="${parts[2]:-}"     # aws|generic|python|...

    # Item name depends on kind
    local name=""
    if [[ "$kind" == "agents" ]]; then
      name="${parts[3]%.md}"
    elif [[ "$kind" == "skills" ]]; then
      # skills are directories: coding/skills/python/<name>/SKILL.md
      name="${parts[3]:-}"
      [[ -z "$name" ]] && continue
    elif [[ "$kind" == "plugins" || "$kind" == "mcps" ]]; then
      name="${parts[2]:-}"
      [[ -z "$name" ]] && continue
    else
      continue
    fi

    # Apply filters: each filter arg must match somewhere in the rel path
    local match=true
    for f in "${filter_args[@]}"; do
      if [[ "$rel" != *"$f"* ]]; then
        match=false
        break
      fi
    done
    $match || continue

    echo "$kind|$category|$subcategory|$name|$path"
  done < <(
    find "$REPO_ROOT/coding/agents" -name "*.md" -type f 2>/dev/null
    find "$REPO_ROOT/coding/skills" -name "SKILL.md" -type f 2>/dev/null
  )
}

# --- Render menu ---
# Globals filled in:
#   ITEMS[]      - array of "type|cat|subcat|name|path" lines
#   SELECTED[]   - parallel array of 0/1
#   CURSOR       - current cursor position
render_menu() {
  local cursor="$1"
  clear
  print_header
  echo "${DIM}Use ↑/↓ (or j/k) to move, SPACE to toggle, A to select all, N to clear,${RESET}"
  echo "${DIM}ENTER to proceed, q to quit.${RESET}"
  echo

  local last_kind=""
  local last_subcategory=""
  local idx=0
  for line in "${ITEMS[@]}"; do
    IFS='|' read -r kind cat subcat name path <<< "$line"

    # Section header on change
    if [[ "$kind" != "$last_kind" ]]; then
      echo
      echo "${BOLD}${BLUE}━━ ${kind^^} ━━${RESET}"
      last_kind="$kind"
      last_subcategory=""
    fi
    if [[ "$subcat" != "$last_subcategory" ]]; then
      echo "${CYAN}  [$subcat]${RESET}"
      last_subcategory="$subcat"
    fi

    local marker checkbox prefix suffix
    if [[ "${SELECTED[$idx]}" == "1" ]]; then
      checkbox="${GREEN}[✓]${RESET}"
    else
      checkbox="[ ]"
    fi

    if [[ "$idx" == "$cursor" ]]; then
      prefix="${BOLD}${YELLOW}▸${RESET} "
      suffix="${RESET}"
    else
      prefix="  "
      suffix=""
    fi

    printf "    %s%s %s${suffix}\n" "$prefix" "$checkbox" "$name"
    idx=$((idx + 1))
  done

  echo
  local sel_count=0
  for s in "${SELECTED[@]}"; do
    [[ "$s" == "1" ]] && sel_count=$((sel_count + 1))
  done
  echo "${BOLD}Selected: $sel_count / ${#ITEMS[@]}${RESET}"
}

# --- Read a single key ---
read_key() {
  local key
  IFS= read -rsn1 key
  if [[ "$key" == $'\e' ]]; then
    IFS= read -rsn2 -t 0.01 key2 || true
    case "$key2" in
      '[A') echo "up" ;;
      '[B') echo "down" ;;
      *) echo "esc" ;;
    esac
  else
    case "$key" in
      ' ') echo "space" ;;
      $'\n'|'') echo "enter" ;;
      'k'|'K') echo "up" ;;
      'j'|'J') echo "down" ;;
      'a'|'A') echo "all" ;;
      'n'|'N') echo "none" ;;
      'q'|'Q') echo "quit" ;;
      *) echo "$key" ;;
    esac
  fi
}

# --- Choose install level ---
choose_level() {
  clear
  print_header
  echo "${BOLD}Choose installation level:${RESET}"
  echo
  echo "  ${BOLD}1)${RESET} User level   (${CYAN}$USER_CLAUDE_DIR${RESET})"
  echo "       Available in every project."
  echo
  echo "  ${BOLD}2)${RESET} Project level (${CYAN}$PROJECT_CLAUDE_DIR${RESET})"
  echo "       Only this project."
  echo
  echo "  ${BOLD}q)${RESET} Cancel"
  echo
  local choice
  while true; do
    read -rp "Choice [1/2/q]: " choice
    case "$choice" in
      1) echo "user"; return ;;
      2) echo "project"; return ;;
      q|Q) echo "cancel"; return ;;
      *) echo "Invalid choice." ;;
    esac
  done
}

# --- Install a single item via symlink ---
install_item() {
  local kind="$1" name="$2" src="$3" target_root="$4"
  local target_dir target_path

  case "$kind" in
    agents) target_dir="$target_root/agents"; target_path="$target_dir/$name.md" ;;
    skills) target_dir="$target_root/skills"; target_path="$target_dir/$name"
            # For skills, src is the SKILL.md; we link the parent dir
            src="$(dirname "$src")"
            ;;
    plugins) target_dir="$target_root/plugins"; target_path="$target_dir/$name" ;;
    mcps)    target_dir="$target_root/mcps"; target_path="$target_dir/$name" ;;
    *) echo "${RED}Unknown kind: $kind${RESET}"; return 1 ;;
  esac

  mkdir -p "$target_dir"

  if [[ -L "$target_path" || -e "$target_path" ]]; then
    echo "  ${YELLOW}⊙${RESET} $kind/$name ${DIM}(already installed — replacing)${RESET}"
    rm -rf "$target_path"
  fi

  ln -s "$src" "$target_path"
  echo "  ${GREEN}✓${RESET} $kind/$name"
}

# --- Main ---
main() {
  # Handle flags
  case "${1:-}" in
    -h|--help) print_help; exit 0 ;;
    --list)
      shift
      echo "${BOLD}Available items:${RESET}"
      discover_items "$@" | awk -F'|' '{printf "  %-10s %-15s %s\n", $1, $3, $4}' | sort -u
      exit 0
      ;;
  esac

  # Discover items
  mapfile -t ITEMS < <(discover_items "$@")
  if [[ ${#ITEMS[@]} -eq 0 ]]; then
    echo "${RED}No items match filter: $*${RESET}"
    echo "Try: ./install.sh --list"
    exit 1
  fi

  # Initialize SELECTED array
  SELECTED=()
  for _ in "${ITEMS[@]}"; do SELECTED+=("0"); done

  # Interactive menu loop
  local cursor=0
  while true; do
    render_menu "$cursor"
    local key
    key=$(read_key)
    case "$key" in
      up)    ((cursor > 0)) && cursor=$((cursor - 1)) ;;
      down)  ((cursor < ${#ITEMS[@]} - 1)) && cursor=$((cursor + 1)) ;;
      space)
        if [[ "${SELECTED[$cursor]}" == "1" ]]; then
          SELECTED[$cursor]=0
        else
          SELECTED[$cursor]=1
        fi
        ;;
      all)   for i in "${!SELECTED[@]}"; do SELECTED[$i]=1; done ;;
      none)  for i in "${!SELECTED[@]}"; do SELECTED[$i]=0; done ;;
      enter) break ;;
      quit)  clear; echo "Cancelled."; exit 0 ;;
    esac
  done

  # Check that something is selected
  local any_selected=false
  for s in "${SELECTED[@]}"; do
    [[ "$s" == "1" ]] && any_selected=true && break
  done
  if ! $any_selected; then
    clear
    echo "${YELLOW}Nothing selected. Exiting.${RESET}"
    exit 0
  fi

  # Choose install level
  local level
  level=$(choose_level)
  if [[ "$level" == "cancel" ]]; then
    echo "Cancelled."
    exit 0
  fi

  local target_root
  if [[ "$level" == "user" ]]; then
    target_root="$USER_CLAUDE_DIR"
  else
    target_root="$PROJECT_CLAUDE_DIR"
  fi

  # Install selected items
  clear
  print_header
  echo "${BOLD}Installing to: ${CYAN}$target_root${RESET}"
  echo

  local installed=0
  for i in "${!ITEMS[@]}"; do
    [[ "${SELECTED[$i]}" != "1" ]] && continue
    IFS='|' read -r kind cat subcat name path <<< "${ITEMS[$i]}"
    install_item "$kind" "$name" "$path" "$target_root"
    installed=$((installed + 1))
  done

  echo
  echo "${GREEN}${BOLD}Done.${RESET} Installed $installed item(s)."
  echo
  echo "${DIM}Tip: items are symlinked — edits in the repo apply everywhere.${RESET}"
}

main "$@"
