"""Test webapp startup."""
import sys
import traceback

try:
    print("Importing webapp...")
    import webapp
    
    print("Creating app...")
    app = webapp.create_app()
    
    print(f"App created successfully!")
    print(f"PORT config: {app.config.get('PORT')}")
    print(f"HOST config: {app.config.get('HOST')}")
    
    print("\nStarting server...")
    webapp.main()
    
except Exception as e:
    print(f"\nERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
