import sqlite3
from ..models import Voter, Candidate, Role
import logging


database_logger = logging.getLogger(__name__)
database_logger.setLevel(logging.INFO)
handler = logging.FileHandler('./app/logs/database.log')
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
database_logger.addHandler(handler)


class DatabaseHandler:
    def __init__(self, db_name: str):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.conn.rollback()
        self.conn.close()
        return False

    def close_connection(self):
        self.conn.close()

    def get_voters(self):
        self.cursor.execute('SELECT * FROM voters')
        return self.cursor.fetchall()

    def count_voters(self):
        self.cursor.execute('SELECT COUNT(*) FROM voters')
        return self.cursor.fetchone()

    def count_voters_by_promotion(self):
        self.cursor.execute('SELECT promotion, COUNT(*) FROM voters GROUP BY promotion')
        return self.cursor.fetchall()

    def get_voter_by_email(self, email: str):
        self.cursor.execute('SELECT * FROM voters WHERE email = ?', (email,))
        return self.cursor.fetchone()

    @staticmethod
    def get_voter_by_link(link_string: str):
        return Voter.query.filter_by(link_string=link_string).first()

    def add_voter(self, voter: Voter):
        self.cursor.execute('INSERT INTO voters (last_name, first_name, email, promotion, voted, link_string, '
                            'secret, invitation_sent, link_sent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (voter.last_name, voter.first_name, voter.email, voter.promotion, voter.voted,
                             voter.link_string, voter.secret, voter.invitation_sent, voter.link_sent))
        database_logger.info(f"Added voter {voter.email}")
        self.conn.commit()

    def delete_voter(self, voter_id: int):
        self.cursor.execute('DELETE FROM voters WHERE id = ?', (voter_id,))
        self.conn.commit()
        database_logger.info(f"Deleted voter {voter_id}")

    def get_roles(self):
        self.cursor.execute('SELECT * FROM roles ORDER BY display_order, name')
        return self.cursor.fetchall()

    def get_role(self, role_id: int):
        self.cursor.execute('SELECT * FROM roles WHERE id = ?', (role_id,))
        return self.cursor.fetchone()

    def add_role(self, name: str, display_order: int = 0):
        self.cursor.execute('INSERT INTO roles (name, display_order) VALUES (?, ?)', (name, display_order))
        self.conn.commit()
        database_logger.info(f"Added role {name}")

    def update_role(self, role_id: int, name: str, display_order: int):
        self.cursor.execute('UPDATE roles SET name = ?, display_order = ? WHERE id = ?',
                            (name, display_order, role_id))
        self.conn.commit()
        database_logger.info(f"Updated role {role_id}")

    def delete_role(self, role_id: int):
        self.cursor.execute('DELETE FROM roles WHERE id = ?', (role_id,))
        self.conn.commit()
        database_logger.info(f"Deleted role {role_id}")

    def get_candidates(self):
        self.cursor.execute('SELECT * FROM candidates')
        return self.cursor.fetchall()

    def get_candidates_with_role(self):
        self.cursor.execute('''
            SELECT c.id, c.name, c.eligible, c.logo, c.role_id, r.name
            FROM candidates c
            LEFT JOIN roles r ON c.role_id = r.id
            ORDER BY r.display_order, r.name, c.name
        ''')
        return self.cursor.fetchall()

    def get_candidate(self, candidate_id: int):
        self.cursor.execute('SELECT * FROM candidates WHERE id = ?', (candidate_id,))
        return self.cursor.fetchone()

    def add_candidate(self, candidate: Candidate):
        self.cursor.execute('INSERT INTO candidates (name, eligible, logo, role_id) VALUES (?, ?, ?, ?)',
                            (candidate.name, True, candidate.logo or '', candidate.role_id))
        self.conn.commit()
        database_logger.info(f"Added candidate {candidate.name}")

    def update_candidate(self, candidate_id: int, name: str, logo: str, role_id=None):
        self.cursor.execute('UPDATE candidates SET name = ?, logo = ?, role_id = ? WHERE id = ?',
                            (name, logo, role_id, candidate_id))
        self.conn.commit()
        database_logger.info(f"Updated candidate {candidate_id}")

    def delete_candidate(self, candidate_id: int):
        self.cursor.execute('DELETE FROM candidates WHERE id = ?', (candidate_id,))
        self.conn.commit()
        database_logger.info(f"Deleted candidate {candidate_id}")

    def get_votes(self):
        self.cursor.execute('SELECT ballot FROM voters WHERE voted = 1')
        return self.cursor.fetchall()

    def count_votes(self):
        self.cursor.execute('SELECT COUNT(*) FROM voters WHERE voted = 1')
        return self.cursor.fetchone()

    def count_votes_by_promotion(self):
        self.cursor.execute('SELECT promotion, COUNT(*) FROM voters WHERE voted = 1 GROUP BY promotion')
        return self.cursor.fetchall()

    def add_vote(self, voter: Voter, ballot: bytes):
        self.cursor.execute('UPDATE voters SET ballot = ? WHERE id = ?', (ballot, voter.id,))
        self.cursor.execute('UPDATE voters SET voted = 1 WHERE id = ?', (voter.id,))
        self.conn.commit()
