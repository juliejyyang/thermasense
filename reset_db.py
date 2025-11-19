import backend.db as db_module

db_module.connect_db()

# Drop all collections
db_module.db.patients.drop()
db_module.db.raw_readings.drop()
db_module.db.variability_scores.drop()
db_module.db.alerts.drop()

print("✓ Database reset!")