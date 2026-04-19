#!/bin/bash

# Logging utility functions
# Provides structured logging with levels and timestamps

# Source colors if not already loaded
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
source "${SCRIPT_DIR}/colors.sh" 2>/dev/null || true

# Log levels
LOG_LEVEL_DEBUG=0
LOG_LEVEL_INFO=1
LOG_LEVEL_WARNING=2
LOG_LEVEL_ERROR=3
LOG_LEVEL_SUCCESS=4

# Current log level (default: INFO)
CURRENT_LOG_LEVEL=${CURRENT_LOG_LEVEL:-1}

# Log file (optional)
LOG_FILE=${LOG_FILE:-""}

# Timestamp format
get_timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

# Write to log file if configured
write_to_file() {
  local message="$1"
  if [ -n "$LOG_FILE" ]; then
    echo "[$(get_timestamp)] $message" >> "$LOG_FILE"
  fi
}

# Debug message
print_debug() {
  local message="$1"
  if [ $CURRENT_LOG_LEVEL -le $LOG_LEVEL_DEBUG ]; then
    echo -e "${HI_BLACK}[DEBUG]${NC} $(get_timestamp) - $message"
    write_to_file "[DEBUG] $message"
  fi
}

# Info message
print_status() {
  local message="$1"
  if [ $CURRENT_LOG_LEVEL -le $LOG_LEVEL_INFO ]; then
    echo -e "${BLUE}[INFO]${NC} $message"
    write_to_file "[INFO] $message"
  fi
}

# Warning message
print_warning() {
  local message="$1"
  if [ $CURRENT_LOG_LEVEL -le $LOG_LEVEL_WARNING ]; then
    echo -e "${YELLOW}[WARNING]${NC} $message"
    write_to_file "[WARNING] $message"
  fi
}

# Error message
print_error() {
  local message="$1"
  if [ $CURRENT_LOG_LEVEL -le $LOG_LEVEL_ERROR ]; then
    echo -e "${RED}[ERROR]${NC} $message" >&2
    write_to_file "[ERROR] $message"
  fi
}

# Success message
print_success() {
  local message="$1"
  echo -e "${GREEN}[SUCCESS]${NC} $message"
  write_to_file "[SUCCESS] $message"
}

# Section header
print_section() {
  local title="$1"
  echo
  echo -e "${BOLD_BLUE}═══════════════════════════════════════════════════════${NC}"
  echo -e "${BOLD_BLUE}  $title${NC}"
  echo -e "${BOLD_BLUE}═══════════════════════════════════════════════════════${NC}"
  write_to_file "=== $title ==="
}

# Progress indicator
print_progress() {
  local current="$1"
  local total="$2"
  local message="${3:-Processing}"
  local percent=$((current * 100 / total))
  
  echo -ne "\r${CYAN}[PROGRESS]${NC} $message: [$current/$total] ${percent}%"
  
  if [ "$current" -eq "$total" ]; then
    echo  # New line when complete
  fi
}

# Spinner for long-running operations
spinner() {
  local pid=$1
  local message="${2:-Processing}"
  local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  local temp
  
  echo -n "${CYAN}[RUNNING]${NC} $message "
  
  while kill -0 $pid 2>/dev/null; do
    temp=${spinstr#?}
    printf "[%c]" "$spinstr"
    spinstr=$temp${spinstr%"$temp"}
    sleep 0.1
    printf "\b\b\b"
  done
  
  printf "\b\b\b   \b\b\b"
  echo
}

# Ask for confirmation
confirm() {
  local message="${1:-Continue?}"
  local default="${2:-n}"
  
  local prompt
  if [ "$default" = "y" ]; then
    prompt="$message [Y/n]: "
  else
    prompt="$message [y/N]: "
  fi
  
  read -r -p "$prompt" response
  
  case "$response" in
    [yY][eE][sS]|[yY])
      return 0
      ;;
    [nN][oO]|[nN])
      return 1
      ;;
    "")
      if [ "$default" = "y" ]; then
        return 0
      else
        return 1
      fi
      ;;
    *)
      return 1
      ;;
  esac
}

# Set log level
set_log_level() {
  local level="$1"
  case "$level" in
    debug|DEBUG)
      CURRENT_LOG_LEVEL=$LOG_LEVEL_DEBUG
      ;;
    info|INFO)
      CURRENT_LOG_LEVEL=$LOG_LEVEL_INFO
      ;;
    warning|WARNING|warn|WARN)
      CURRENT_LOG_LEVEL=$LOG_LEVEL_WARNING
      ;;
    error|ERROR)
      CURRENT_LOG_LEVEL=$LOG_LEVEL_ERROR
      ;;
    *)
      print_warning "Unknown log level: $level"
      ;;
  esac
}

# Initialize log file
init_log_file() {
  local log_file="$1"
  LOG_FILE="$log_file"
  
  # Create log directory if it doesn't exist
  local log_dir=$(dirname "$log_file")
  if [ ! -d "$log_dir" ]; then
    mkdir -p "$log_dir"
  fi
  
  # Initialize log file
  echo "=== Log started at $(get_timestamp) ===" > "$LOG_FILE"
}

# Export functions
export -f print_debug print_status print_warning print_error print_success
export -f print_section print_progress spinner confirm
export -f set_log_level init_log_file get_timestamp write_to_file
