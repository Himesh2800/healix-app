import tensorflow as tf
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2, preprocess_input, decode_predictions
from tensorflow.keras.preprocessing import image
import numpy as np
import os

class SkinDiseaseModel:
    def __init__(self):
        self.model = None
        self.load_model()

    def load_model(self):
        try:
            # Load MobileNetV2 pre-trained on ImageNet
            print("Loading MobileNetV2 model...")
            self.model = MobileNetV2(weights='imagenet')
            print("MobileNetV2 model loaded successfully.")
        except Exception as e:
            print(f"Error loading model: {e}")
            self.model = None

    def predict(self, img_path):
        if not self.model:
            return {"error": "Model not loaded"}

        try:
            # Load and preprocess image
            img = image.load_img(img_path, target_size=(224, 224))
            x = image.img_to_array(img)
            x = np.expand_dims(x, axis=0)
            x = preprocess_input(x)

            # Run inference
            preds = self.model.predict(x)
            
            # Decode predictions (returns list of tuples (class_id, class_name, probability))
            # We take the top 3 predictions
            decoded_preds = decode_predictions(preds, top=3)[0]
            
            results = []
            for _, label, prob in decoded_preds:
                results.append({
                    "name": label.replace("_", " ").title(),
                    "probability": float(prob) * 100,
                    "recommendation": "Consult a dermatologist for accurate diagnosis." # Generic recommendation
                })
                
            return results

        except Exception as e:
            print(f"Prediction error: {e}")
            return {"error": str(e)}
