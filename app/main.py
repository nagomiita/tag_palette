from db.init import dispose_engine, initialize_database
from gui.app import App

if __name__ == "__main__":
    initialize_database()
    app = App()
    try:
        app.mainloop()
    finally:
        dispose_engine()
