"""Run the local Flask gateway; models load only when AI_ENABLED=true."""
from webapp import create_app, main

if __name__ == "__main__":
    main()
