import re

class UserModel:
    def __init__(self, name=None, email=None, id=None):
        self.id = id
        self.name = name
        self.email = email

    @staticmethod
    def validate_name(name):
        if not name or not isinstance(name, str) or len(name) < 3:
            return False, "Debe tener al menos 3 caracteres."
        return True, None

    @staticmethod
    def validate_email(email):
        regex = r'^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w+$'
        if not email or not re.match(regex, email):
            return False, "Formato no válido."
        return True, None

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email}

    @staticmethod
    def from_row(row):
        """Convierte una fila de la base de datos (id, name, email) en un objeto UserModel."""
        if not row: return None
        return UserModel(id=row[0], name=row[1], email=row[2])