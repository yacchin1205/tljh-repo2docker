from datetime import datetime
import sqlite3


class TokenStore:
    def __init__(self, dbpath):
        self.conn = sqlite3.connect(dbpath)
        self._prepare_tables()

    def set(self, current_user, repo, token):
        cur = self.conn.cursor()
        if self._select_by(cur, current_user, repo) is None:
            cur.execute("""
INSERT INTO repo_tokens (user, repo, token, updated) VALUES (?, ?, ?, ?);
            """, (current_user.name, repo, token, datetime.now()))
        else:
            cur.execute("""
UPDATE repo_tokens SET token=?, updated=? WHERE user=? AND repo=?;
            """, (token, datetime.now(), current_user.name, repo))
        self.conn.commit()

    def get(self, current_user, repo):
        cur = self.conn.cursor()
        return self._select_by(cur, current_user, repo)
        
    def _prepare_tables(self):
        """
        Create tables for TokenStore
        """
        cur = self.conn.cursor()
        cur.execute("""
CREATE TABLE IF NOT EXISTS repo_tokens (user text, repo text, token text, updated datetime);
        """)
        self.conn.commit()
    
    def _select_by(self, cur, current_user, repo):
        """
        Select repo_token for specified user and repo
        """
        result = cur.execute("""
SELECT token FROM repo_tokens WHERE user=? AND repo=? ORDER BY updated DESC LIMIT 1;
        """, (current_user.name, repo)).fetchone()
        if result is None:
            return None
        return result[0]

