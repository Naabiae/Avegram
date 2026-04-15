import sys
from signal_telegram import main, db_init

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("migrate", "--migrate"):
        db_init()
        print("db_init ok")
    else:
        main()

