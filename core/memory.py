import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from config.settings import SETTINGS

class Memory:
    def __init__(self, db_path: str = "swissbrain.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    user_message TEXT,
                    intent TEXT,
                    modules_used TEXT,
                    response_summary TEXT,
                    priority TEXT
                );
                
                CREATE TABLE IF NOT EXISTS user_interests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT UNIQUE,
                    category TEXT,
                    relevance_score REAL DEFAULT 0.5,
                    last_mentioned TEXT
                );
                
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_type TEXT,
                    name TEXT,
                    parameters TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    triggered_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module TEXT,
                    title TEXT,
                    content TEXT,
                    priority TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    notified_at TEXT,
                    user_feedback TEXT
                );
                
                CREATE TABLE IF NOT EXISTS correlations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    finding_1_id INTEGER,
                    finding_2_id INTEGER,
                    correlation_type TEXT,
                    confidence REAL,
                    description TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
    
    def log_interaction(self, user_message: str, intent: str, 
                       modules_used: List[str], response_summary: str, 
                       priority: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO interactions 
                (user_message, intent, modules_used, response_summary, priority)
                VALUES (?, ?, ?, ?, ?)
            """, (user_message, intent, json.dumps(modules_used), 
                  response_summary, priority))
    
    def add_interest(self, topic: str, category: str = "general"):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO user_interests (topic, category, last_mentioned)
                VALUES (?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                    relevance_score = relevance_score + 0.1,
                    last_mentioned = ?
            """, (topic, category, datetime.now().isoformat(), 
                  datetime.now().isoformat()))
    
    def get_interests(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM user_interests ORDER BY relevance_score DESC"
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def add_finding(self, module: str, title: str, content: str, 
                    priority: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO findings (module, title, content, priority)
                VALUES (?, ?, ?, ?)
            """, (module, title, content, priority))
            return cursor.lastrowid
    
    def get_pending_findings(self, min_priority: str = "baja") -> List[Dict]:
        priority_order = {"critica": 0, "alta": 1, "media": 2, "baja": 3}
        min_level = priority_order.get(min_priority, 3)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM findings 
                WHERE status = 'pending' 
                AND notified_at IS NULL
                ORDER BY created_at DESC
            """)
            findings = [dict(row) for row in cursor.fetchall()]
            return [f for f in findings 
                    if priority_order.get(f['priority'], 3) <= min_level]
    
    def mark_notified(self, finding_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE findings 
                SET notified_at = ?, status = 'notified'
                WHERE id = ?
            """, (datetime.now().isoformat(), finding_id))
    
    def add_alert(self, alert_type: str, name: str, parameters: Dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO alerts (alert_type, name, parameters)
                VALUES (?, ?, ?)
            """, (alert_type, name, json.dumps(parameters)))
    
    def get_active_alerts(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM alerts WHERE status = 'active'"
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def add_correlation(self, finding_1_id: int, finding_2_id: int,
                       correlation_type: str, confidence: float,
                       description: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO correlations 
                (finding_1_id, finding_2_id, correlation_type, confidence, description)
                VALUES (?, ?, ?, ?, ?)
            """, (finding_1_id, finding_2_id, correlation_type, 
                  confidence, description))