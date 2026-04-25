import os
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.metrics import mean_squared_error, accuracy_score, classification_report

print("🚀 INITIALIZING AAPSLS ML PIPELINE...")

# 1. Load the Ultimate Dataset
data_path = 'data/AAPSLS_Ultimate_Training_Dataset.csv'
if not os.path.exists(data_path):
    raise FileNotFoundError(f"Missing dataset at {data_path}. Please move the CSV into the data/ folder.")

df = pd.read_csv(data_path)

# 2. SEPARATE AND EXPORT THE TRAINING AND TESTING DATA
# We split the entire dataframe first so you have an exact, auditable record of the data splits.
train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)

# Save the splits for later examination
train_export_path = 'data/AAPSLS_Model_Train_Split.csv'
test_export_path = 'data/AAPSLS_Model_Test_Split.csv'

train_df.to_csv(train_export_path, index=False)
test_df.to_csv(test_export_path, index=False)

print(f"📁 Exported Training Data ({len(train_df)} rows) to: {train_export_path}")
print(f"📁 Exported Testing Data ({len(test_df)} rows) to: {test_export_path}")

# 3. Define Features (Inputs / X)
numeric_features = [
    'traffic_congestion_level', 'weather_condition_severity', 
    'route_risk_level', 'driver_behavior_score', 
    'disruption_likelihood_score', 'Assigned_Payload_kg', 
    'Base_Speed_kmph', 'Volumetric_Factor'
]

categorical_features = [
    'Transport_Mode', 'Speed_Category'
]

# Extract X and Y specifically from the frozen splits
X_train = train_df[numeric_features + categorical_features]
X_test = test_df[numeric_features + categorical_features]

# 4. Define Targets (Outputs / Y)
regression_targets = [
    'eta_variation_hours', 
    'Dynamic_Shipping_Cost', 
    'Adjusted_Fuel_Consumption', 
    'Cargo_Damage_Score', 
    'Estimated_Carbon_Emissions_kg'
]

classification_targets = [
    'risk_classification', 
    'Optimal_Reroute_Trigger', 
    'Maintenance_Required_Flag'
]

# 5. Build the Preprocessing Transformer
preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), numeric_features),
        ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_features)
    ])

# 6. Create Directory for Saved Models
os.makedirs('models', exist_ok=True)

print("\n⚙️  TRAINING REGRESSION MODELS (Physics & Pricing)...")
for target in regression_targets:
    y_train = train_df[target]
    y_test = test_df[target]
    
    # Build Pipeline: Preprocess -> Random Forest Regressor
    pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('regressor', RandomForestRegressor(n_estimators=50, random_state=42, n_jobs=-1))
    ])
    
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    
    # Save Model
    joblib.dump(pipeline, f'models/{target}_model.pkl')
    print(f"  ✅ {target} | RMSE: {rmse:.4f}")

print("\n🧠 TRAINING CLASSIFICATION MODELS (Agentic Triggers)...")
for target in classification_targets:
    y_train = train_df[target]
    y_test = test_df[target]
    
    # Build Pipeline: Preprocess -> Random Forest Classifier
    pipeline = Pipeline(steps=[
        ('preprocessor', preprocessor),
        ('classifier', RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=-1))
    ])
    
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    # Save Model
    joblib.dump(pipeline, f'models/{target}_model.pkl')
    print(f"  ✅ {target} | Accuracy: {acc*100:.2f}%")

print("\n🎯 TRAINING COMPLETE. All models saved to the /models directory!")