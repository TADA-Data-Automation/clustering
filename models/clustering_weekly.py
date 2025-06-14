import pandas as pd
import numpy as np
import re
from datetime import timedelta
from pathlib import Path
from utils.helpers import Query

# Load model definitions
MODELS_DIR = Path(__file__).resolve().parent

scaler_def = pd.read_csv(MODELS_DIR / "scaler_definitions.csv")
scaler_mean = scaler_def.set_index("Feature")["Mean"]
scaler_var = scaler_def.set_index("Feature")["Variance"]

cluster_def = pd.read_csv(MODELS_DIR / "cluster_definitions.csv")
cluster_def['Centroid'] = cluster_def['Centroid'].apply(lambda x: [float(i) for i in re.findall(r"[-+]?\d*\.\d+|\d+", x)])
cluster_centroids = np.array(cluster_def['Centroid'].tolist())
cluster_labels = dict(zip(cluster_def["Cluster"], cluster_def["Description"]))

def scale_features(df):
    for feature in scaler_mean.index:
        if feature in df.columns:
            df[feature + "_scaled"] = (df[feature] - scaler_mean[feature]) / np.sqrt(scaler_var[feature])
    return df


def assign_clusters(df):
    X = df[['frequency_scaled', 'total_scaled', 'rate_scaled']].values
    distances = np.linalg.norm(X[:, None, :] - cluster_centroids[None, :, :], axis=2)
    df['Cluster'] = distances.argmin(axis=1)
    return df


def get_redash_data(start, end, redash, query_id, return_cluster_stats=False):
    start_str, end_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    print(f"Querying Redash: {start_str} → {end_str}")

    redash.run_query(Query(query_id, params={"date_range": {"start": start_str, "end": end_str}}))
    results = redash.get_result(query_id)
    df = pd.DataFrame(results)

    if df.empty:
        print("No data returned.")
        return (pd.DataFrame(), pd.DataFrame()) if return_cluster_stats else pd.DataFrame()

    required = ['rider_uuid', 'frequency', 'total']
    if any(col not in df.columns for col in required):
        print(f"Missing columns: {required}")
        return (pd.DataFrame(), pd.DataFrame()) if return_cluster_stats else pd.DataFrame()

    agg_df = df.groupby('rider_uuid').agg(
        frequency=('frequency', 'sum'),
        total=('total', 'sum')
    ).reset_index()
    
    agg_df = agg_df[agg_df['frequency'] > 0]
    agg_df['rate'] = agg_df['total'] / agg_df['frequency']
    agg_df = agg_df.dropna(subset=['rate'])

    agg_df = scale_features(agg_df)
    agg_df = assign_clusters(agg_df)
    agg_df['Cluster_Description'] = agg_df['Cluster'].map(cluster_labels)

    print(f"Clustered {len(agg_df)} riders (aggregated from {len(df)} rows)")

    if return_cluster_stats:
        cluster_stats = agg_df.groupby('Cluster_Description').agg({
            'total': 'sum'
        }).round(2).T
        cluster_stats.index = [(end + timedelta(days=1)).strftime("%Y-%m-%d")]
        return agg_df, cluster_stats

    return agg_df

