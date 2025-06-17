import os
import psycopg2
import pandas as pd

# --- Konfiguracja połączenia z QuestDB ---
DB_HOST = os.environ.get('QUESTDB_HOST', 'localhost')
DB_PORT = int(os.environ.get('QUESTDB_PORT', '8812'))
DB_NAME = os.environ.get('QUESTDB_DB', 'qdb')
DB_USER = os.environ.get('QUESTDB_USER', 'admin')
DB_PASSWORD = os.environ.get('QUESTDB_PASSWORD', 'quest')

PROJECT_ROOT = '/data'

# Ścieżki do trajektorii
CSV_F_TRAJECTORY = os.path.join(PROJECT_ROOT, "F_trajectories", "trajectory.csv")
CSV_I_TRAJECTORY = os.path.join(PROJECT_ROOT, "I_trajectories", "trajectory.csv")

# Ścieżki do folderów z obrazami
IMAGES_F = os.path.join(PROJECT_ROOT, "F_trajectories", "camera_images")
IMAGES_I_POINTGREY = os.path.join(PROJECT_ROOT, "I_trajectories", "pointgrey_camera_images")
IMAGES_I_PHONE = os.path.join(PROJECT_ROOT, "I_trajectories", "phone_camera_images")  # Jeśli używasz

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def initialize_tables(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS trajectories;")
    cur.execute("DROP TABLE IF EXISTS camera_images;")

    cur.execute("""
        CREATE TABLE trajectories (
            ts TIMESTAMP,
            pos_x DOUBLE, pos_y DOUBLE, pos_z DOUBLE,
            orientation_x DOUBLE, orientation_y DOUBLE, orientation_z DOUBLE, orientation_w DOUBLE,
            linear_vel_x DOUBLE, linear_vel_y DOUBLE, linear_vel_z DOUBLE,
            angular_vel_x DOUBLE, angular_vel_y DOUBLE, angular_vel_z DOUBLE,
            bag_file SYMBOL, trajectory_type SYMBOL
        );
    """)

    cur.execute("""
        CREATE TABLE camera_images (
            timestamp DOUBLE,
            camera_type SYMBOL,
            image_path STRING,
            bag_file SYMBOL
        );
    """)

    conn.commit()
    cur.close()

def import_images(conn, folder, camera_type, bag_file):
    if not os.path.exists(folder):
        print(f"[!] Katalog nie istnieje: {folder}")
        return

    cur = conn.cursor()
    count = 0
    for fname in os.listdir(folder):
        if fname.endswith(".png"):
            try:
                ts = float(fname.split('_')[-1].replace('.png', ''))
                path = os.path.join(folder, fname)
                cur.execute("""
                    INSERT INTO camera_images (timestamp, camera_type, image_path, bag_file)
                    VALUES (%s, %s, %s, %s)
                """, (ts, camera_type, path, bag_file))
                count += 1
            except Exception as e:
                print(f"[!] Błąd pliku {fname}: {e}")
    conn.commit()
    cur.close()
    print(f"[✓] Zaimportowano {count} obrazów z {folder}")

def import_csv(conn, path, bag_file, traj_type):
    if not os.path.exists(path):
        print(f"[!] Brak pliku: {path}")
        return

    df = pd.read_csv(path)
    if df.empty:
        print(f"[!] Pusty plik: {path}")
        return

    # Konwersja timestampu do ISO8601 z mikrosekundami
    df['ts'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    df['ts'] = df['ts'].dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    cur = conn.cursor()
    insert = """
    INSERT INTO trajectories (
        ts, pos_x, pos_y, pos_z,
        orientation_x, orientation_y, orientation_z, orientation_w,
        linear_vel_x, linear_vel_y, linear_vel_z,
        angular_vel_x, angular_vel_y, angular_vel_z,
        bag_file, trajectory_type
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    for _, row in df.iterrows():
        cur.execute(insert, (
            row['ts'],
            row['pos_x'], row['pos_y'], row['pos_z'],
            row['orientation_x'], row['orientation_y'], row['orientation_z'], row['orientation_w'],
            row['linear_vel_x'], row['linear_vel_y'], row['linear_vel_z'],
            row['angular_vel_x'], row['angular_vel_y'], row['angular_vel_z'],
            bag_file, traj_type
        ))

    conn.commit()
    cur.close()
    print(f"[✓] Zaimportowano {len(df)} trajektorii z {path}")

if __name__ == "__main__":
    conn = get_connection()
    initialize_tables(conn)

    # Import obrazów
    import_images(conn, IMAGES_F, 'PointGrey_F_Bag', 'F_trajectories.bag')
    import_images(conn, IMAGES_I_POINTGREY, 'PointGrey_I_Bag', 'I_trajectories.bag')
    import_images(conn, IMAGES_I_PHONE, 'Phone_I_Bag', 'I_trajectories.bag')  # jeśli potrzebne

    # Import trajektorii (z trajectory.csv)
    import_csv(conn, CSV_F_TRAJECTORY, 'F_trajectories.bag', 'slam')
    import_csv(conn, CSV_I_TRAJECTORY, 'I_trajectories.bag', 'slam')

    conn.close()
    print("\n[✓] Wszystkie dane zostały zaimportowane do QuestDB.")
