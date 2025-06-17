import os
import psycopg2
import pandas as pd
from datetime import datetime, timezone

DB_HOST = os.environ.get('DB_HOST')
DB_NAME = os.environ.get('DB_NAME')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')

PROJECT_ROOT_CONTAINER = '/app'
BAG_FILES_DIR_CONTAINER = os.path.join(PROJECT_ROOT_CONTAINER, "bag_files")

IMAGES_F_PATH_CONTAINER = os.path.join(PROJECT_ROOT_CONTAINER, "F_trajectories", "camera_images")
IMAGES_I_PHONE_PATH_CONTAINER = os.path.join(PROJECT_ROOT_CONTAINER, "I_trajectories", "phone_camera_images")
IMAGES_I_POINTGREY_PATH_CONTAINER = os.path.join(PROJECT_ROOT_CONTAINER, "I_trajectories", "pointgrey_camera_images")

CSV_F_GPS_ODOM = os.path.join(PROJECT_ROOT_CONTAINER, "F_trajectories", "gps_odom.csv")
CSV_F_ORB_SLAM3 = os.path.join(PROJECT_ROOT_CONTAINER, "F_trajectories", "orb_slam3.csv")

CSV_I_GPS_ODOM = os.path.join(PROJECT_ROOT_CONTAINER, "I_trajectories", "gps_odom.csv")
CSV_I_ORB_SLAM3_PHONE = os.path.join(PROJECT_ROOT_CONTAINER, "I_trajectories", "orb_slam3_phone.csv")
CSV_I_ORB_SLAM3 = os.path.join(PROJECT_ROOT_CONTAINER, "I_trajectories", "orb_slam3.csv") # Zakładam, że ten jest dla PointGrey

#Funkcja do łączenia z bazą danych 
def get_db_connection():
    conn = None
    try:
        print(f"Próba połączenia z DB_HOST: {DB_HOST}, DB_NAME: {DB_NAME}, DB_USER: {DB_USER}")
        conn = psycopg2.connect(
            host=DB_HOST,
            port=5432,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        print("Połączono z bazą danych MobilityDB pomyślnie!")
        return conn
    except Exception as e:
        print(f"Błąd połączenia z bazą danych: {e}")
        return None

#Funkcja do inicjalizacji tabel w bazie danych
def initialize_db_tables(conn):
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE EXTENSION IF NOT EXISTS postgis;
            CREATE EXTENSION IF NOT EXISTS mobilitydb;
        """)
        conn.commit()
        print("Rozszerzenia PostGIS i MobilityDB zainstalowane/sprawdzone.")

        #Tabela dla informacji o obrazach
        cur.execute("""
            DROP TABLE IF EXISTS camera_images CASCADE;
            CREATE TABLE camera_images (
                id SERIAL PRIMARY KEY,
                timestamp NUMERIC(16, 6) NOT NULL,
                camera_type VARCHAR(50) NOT NULL,
                image_path TEXT NOT NULL,
                bag_file VARCHAR(255) NOT NULL
            );
            CREATE INDEX idx_camera_images_timestamp ON camera_images (timestamp);
        """)
        conn.commit()
        print("Tabela 'camera_images' utworzona.")

        #Zmodyfikowana tabela dla trajektorii
        cur.execute("""
            DROP TABLE IF EXISTS trajectories CASCADE;
            CREATE TABLE trajectories (
                id SERIAL PRIMARY KEY,
                trajectory tgeompoint, -- Główna trajektoria (pozycja X,Y,Z z czasem)
                -- Nowe kolumny temporalne:
                orientation_x tfloat,
                orientation_y tfloat,
                orientation_z tfloat,
                orientation_w tfloat,
                linear_velocity tgeompoint, -- Prędkość liniowa (vx, vy, vz z czasem)
                angular_velocity tgeompoint, -- Prędkość kątowa (ax, ay, az z czasem)
                -- Koniec nowych kolumn
                bag_file VARCHAR(255) NOT NULL,
                trajectory_type VARCHAR(100) NOT NULL
            );
        """)
        conn.commit()
        print("Tabela 'trajectories' utworzona ze zaktualizowanym schematem.")

        cur.close()
    except Exception as e:
        print(f"Błąd podczas inicjalizacji tabel: {e}")
        conn.rollback()

#Funkcja do importu ścieżek obrazów
def import_images_metadata(conn, images_dir_path, camera_type, bag_file_name):
    print(f"\nImportowanie metadanych obrazów z '{images_dir_path}' dla {camera_type}...")
    cur = conn.cursor()
    imported_count = 0
    try:
        if not os.path.exists(images_dir_path):
            print(f" Katalog obrazów nie istnieje: {images_dir_path}.")
            return

        for filename in os.listdir(images_dir_path):
            if filename.endswith(".png"):
                try:
                    timestamp_str = filename.split('_')[-1].replace('.png', '')
                    timestamp = float(timestamp_str) 

                    full_image_path_in_container = os.path.join(images_dir_path, filename)

                    cur.execute("""
                        INSERT INTO camera_images (timestamp, camera_type, image_path, bag_file)
                        VALUES (%s, %s, %s, %s)
                    """, (timestamp, camera_type, full_image_path_in_container, bag_file_name))
                    imported_count += 1
                except ValueError:
                    print(f"Pominięto plik '{filename}'")
                except Exception as e:
                    print(f"Błąd podczas wstawiania metadanych obrazu '{filename}': {e}")
                    conn.rollback() 
        conn.commit()
        print(f"Zaimportowano {imported_count} metadanych obrazów dla {camera_type}.")
    except Exception as e:
        print(f"Błąd ogólny podczas przetwarzania katalogu {images_dir_path}: {e}")
        conn.rollback()
    finally:
        cur.close()


#Funkcja do importu danych trajektorii z CSV 
def import_trajectory_data(conn, csv_file_path, bag_file_name, trajectory_type):
    print(f"\nImportowanie danych trajektorii z '{csv_file_path}' (typ: {trajectory_type})...")
    cur = conn.cursor()

    try:
        if not os.path.exists(csv_file_path):
            print(f" Plik CSV nie znaleziony: {csv_file_path}. Pomijam import trajektorii dla {trajectory_type}.")
            return

        df = pd.read_csv(csv_file_path)
        print(f"Wczytano {len(df)} wierszy danych trajektorii z {csv_file_path}.")
        if df.empty:
            print(f"Plik CSV {csv_file_path} jest pusty. Pomijam import trajektorii.")
            return

        df['full_timestamp'] = df['header.stamp.secs'] + df['header.stamp.nsecs'] / 1e9
        df = df.sort_values(by='full_timestamp').reset_index(drop=True)

        # Listy do przechowywania temporalnych ciągów WKT dla każdej kolumny
        wkt_trajectory_points = []
        wkt_orientation_x_points = []
        wkt_orientation_y_points = []
        wkt_orientation_z_points = []
        wkt_orientation_w_points = []
        wkt_linear_velocity_points = []
        wkt_angular_velocity_points = []

        has_orientation = all(col in df.columns for col in ['pose.pose.orientation.x', 'pose.pose.orientation.y', 'pose.pose.orientation.z', 'pose.pose.orientation.w'])
        has_linear_velocity = all(col in df.columns for col in ['twist.twist.linear.x', 'twist.twist.linear.y', 'twist.twist.linear.z'])
        has_angular_velocity = all(col in df.columns for col in ['twist.twist.angular.x', 'twist.twist.angular.y', 'twist.twist.angular.z'])

        for index, row in df.iterrows():
            try:
                timestamp = row['full_timestamp']
                dt_object = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                iso_timestamp = dt_object.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+00' 

                
                pos_x = row['pose.pose.position.x']
                pos_y = row['pose.pose.position.y']
                pos_z = row['pose.pose.position.z']
                
                wkt_trajectory_points.append(f"POINT Z ({pos_x} {pos_y} {pos_z})@{iso_timestamp}")

            
                if has_orientation:
                    wkt_orientation_x_points.append(f"{row['pose.pose.orientation.x']}@{iso_timestamp}")
                    wkt_orientation_y_points.append(f"{row['pose.pose.orientation.y']}@{iso_timestamp}")
                    wkt_orientation_z_points.append(f"{row['pose.pose.orientation.z']}@{iso_timestamp}")
                    wkt_orientation_w_points.append(f"{row['pose.pose.orientation.w']}@{iso_timestamp}")

                # Dane dla prędkości liniowej (jako tgeompoint)
                if has_linear_velocity:
                    lin_vel_x = row['twist.twist.linear.x']
                    lin_vel_y = row['twist.twist.linear.y']
                    lin_vel_z = row['twist.twist.linear.z']
                    wkt_linear_velocity_points.append(f"POINT Z ({lin_vel_x} {lin_vel_y} {lin_vel_z})@{iso_timestamp}")

                # Dane dla prędkości kątowej (jako tgeompoint)
                if has_angular_velocity:
                    ang_vel_x = row['twist.twist.angular.x']
                    ang_vel_y = row['twist.twist.angular.y']
                    ang_vel_z = row['twist.twist.angular.z']
                    wkt_angular_velocity_points.append(f"POINT Z ({ang_vel_x} {ang_vel_y} {ang_vel_z})@{iso_timestamp}")

            except KeyError as ke:
                print(f"OSTRZEŻENIE: Brak oczekiwanej kolumny '{ke}' w {csv_file_path}. Pomijam wiersz.")
                continue
            except Exception as e:
                print(f"OSTRZEŻENIE: Błąd przetwarzania wiersza {index} z {csv_file_path}: {e}. Pomijam wiersz.")
                continue

        if wkt_trajectory_points:
            #Tworzymy temporalne ciągi WKT dla każdej kolumny
            trajectory_wkt = f"{{{', '.join(wkt_trajectory_points)}}}"

            # Tworzymy stringi temporalne dla kolumn opcjonalnych.
            orientation_x_wkt = f"{{{', '.join(wkt_orientation_x_points)}}}" if wkt_orientation_x_points else None
            orientation_y_wkt = f"{{{', '.join(wkt_orientation_y_points)}}}" if wkt_orientation_y_points else None
            orientation_z_wkt = f"{{{', '.join(wkt_orientation_z_points)}}}" if wkt_orientation_z_points else None
            orientation_w_wkt = f"{{{', '.join(wkt_orientation_w_points)}}}" if wkt_orientation_w_points else None
            linear_velocity_wkt = f"{{{', '.join(wkt_linear_velocity_points)}}}" if wkt_linear_velocity_points else None
            angular_velocity_wkt = f"{{{', '.join(wkt_angular_velocity_points)}}}" if wkt_angular_velocity_points else None

            
            print(f"\n--- DEBUGOWANIE DANYCH DLA '{trajectory_type}' ---")
            print(f"Liczba punktów w wkt_trajectory_points: {len(wkt_trajectory_points)}")
            if len(wkt_trajectory_points) > 0:
                print(f"Pierwszy punkt WKT trajektorii: {wkt_trajectory_points[0]}")
                print(f"Ostatni punkt WKT trajektorii: {wkt_trajectory_points[-1]}")
            else:
                print("Brak punktów do utworzenia trajectory_wkt.")

            if orientation_x_wkt:
                print(f"Liczba punktów WKT orientacji X: {len(wkt_orientation_x_points)}")
                print(f"Pierwsza wartość WKT orientacji X: {wkt_orientation_x_points[0]}")
            
            # Wstawienie trajektorii do tabeli (ze wszystkimi nowymi kolumnami)
            cur.execute("""
                INSERT INTO trajectories (
                    trajectory, bag_file, trajectory_type,
                    orientation_x, orientation_y, orientation_z, orientation_w,
                    linear_velocity, angular_velocity
                )
                VALUES (%s::tgeompoint, %s, %s, %s::tfloat, %s::tfloat, %s::tfloat, %s::tfloat, %s::tgeompoint, %s::tgeompoint);
            """, (
                trajectory_wkt, bag_file_name, trajectory_type,
                orientation_x_wkt, orientation_y_wkt, orientation_z_wkt, orientation_w_wkt,
                linear_velocity_wkt, angular_velocity_wkt
            ))

            conn.commit()
            print(f"Zaimportowano 1 trajektorię dla {bag_file_name} (typ: {trajectory_type}) ze wszystkimi dostępnymi danymi temporalnymi.")
        else:
            print(f"Brak punktów do utworzenia trajektorii z {csv_file_path}. Trajektoria niezaimportowana.")

    except FileNotFoundError:
        print(f"Błąd: Plik CSV nie znaleziony: {csv_file_path}.")
    except pd.errors.EmptyDataError:
        print(f"OSTRZEŻENIE: Plik CSV jest pusty lub uszkodzony: {csv_file_path}.")
    except Exception as e:
        print(f"Ogólny błąd podczas importu trajektorii z {csv_file_path}: {e}")
        conn.rollback()
    finally:
        cur.close()


if __name__ == "__main__":
    conn = get_db_connection()
    if conn:
        initialize_db_tables(conn)

        import_images_metadata(
            conn, IMAGES_F_PATH_CONTAINER, 'PointGrey_F_Bag', 'F_trajectories.bag'
        )

        import_images_metadata(
            conn, IMAGES_I_PHONE_PATH_CONTAINER, 'Phone_I_Bag', 'I_trajectories.bag'
        )
        import_images_metadata(
            conn, IMAGES_I_POINTGREY_PATH_CONTAINER, 'PointGrey_I_Bag', 'I_trajectories.bag'
        )
        #Importowanie danych trajektorii 
        # F_trajectories.bag
        import_trajectory_data(conn, CSV_F_ORB_SLAM3, 'F_trajectories.bag', 'ORB-SLAM3_F_Bag')
        import_trajectory_data(conn, CSV_F_GPS_ODOM, 'F_trajectories.bag', 'GPS-Odom_F_Bag')

        # I_trajectories.bag
        import_trajectory_data(conn, CSV_I_ORB_SLAM3_PHONE, 'I_trajectories.bag', 'ORB-SLAM3_Phone_I_Bag')
        import_trajectory_data(conn, CSV_I_ORB_SLAM3, 'I_trajectories.bag', 'ORB-SLAM3_PointGrey_I_Bag')
        import_trajectory_data(conn, CSV_I_GPS_ODOM, 'I_trajectories.bag', 'GPS-Odom_I_Bag')

        conn.close()
        print("\nPołączenie z bazą danych zostało zamknięte. Wszystkie dostępne dane zostały przetworzone.")
    else:
        print("Nie udało się połączyć z bazą danych. Sprawdź konfigurację w docker-compose.yml i status kontenera MobilityDB.")