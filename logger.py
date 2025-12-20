from colorama import init, Fore, Style
from datetime import datetime

# Initialize colorama
init(autoreset=True)

def _get_timestamp():
    return f"{Fore.LIGHTCYAN_EX}[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

def info(message):
    print(f"{_get_timestamp()} {Fore.BLUE}[INFO]{Style.RESET_ALL} {message}")

def error(message):
    print(f"{_get_timestamp()} {Fore.RED}[ERROR]{Style.RESET_ALL} {message}")

def warning(message):
    print(f"{_get_timestamp()} {Fore.YELLOW}[WARNING]{Style.RESET_ALL} {message}")

def debug(message):
    print(f"{_get_timestamp()} {Fore.MAGENTA}[DEBUG]{Style.RESET_ALL} {message}")

def success(message):
    print(f"{_get_timestamp()} {Fore.GREEN}[SUCCESS]{Style.RESET_ALL} {message}")

def voice(message):
    print(f"{_get_timestamp()} {Fore.CYAN}[VOICE]{Style.RESET_ALL} {message}")
