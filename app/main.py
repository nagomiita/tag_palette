from db.init import initialize_database
from gui.app import App

if __name__ == "__main__":
    initialize_database()
    app = App()
    app.mainloop()
