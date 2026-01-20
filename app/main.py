from app import create_app

wayfinder = create_app()

if __name__ == "__main__":
    wayfinder.run(host="0.0.0.0", port=5000, debug=True)
