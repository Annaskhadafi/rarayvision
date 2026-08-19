import os
import sys
from onnxruntime.quantization import quantize_dynamic, QuantType

def quantize_onnx_model(input_path: str, output_path: str):
    if not os.path.exists(input_path):
        print(f"[!] Input model not found: {input_path}")
        return False

    print(f"[*] Quantizing: {os.path.basename(input_path)} -> {os.path.basename(output_path)} ...")
    try:
        quantize_dynamic(
            model_input=input_path,
            model_output=output_path,
            weight_type=QuantType.QInt8
        )
        orig_size = os.path.getsize(input_path) / (1024 * 1024)
        new_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[OK] Success: {os.path.basename(output_path)} created! ({orig_size:.2f} MB -> {new_size:.2f} MB, {((orig_size-new_size)/orig_size)*100:.1f}% reduction)")
        return True
    except Exception as e:
        print(f"[ERROR] Quantization error for {input_path}: {e}")
        return False

if __name__ == "__main__":
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    models_dir = os.path.join(base_dir, "ml_models")

    # 1. Anti-Spoof
    spoof_in = os.path.join(models_dir, "MiniFASNetV2.onnx")
    spoof_out = os.path.join(models_dir, "MiniFASNetV2_int8.onnx")
    quantize_onnx_model(spoof_in, spoof_out)

    # 2. Emotion
    emotion_in = os.path.join(models_dir, "emotion-ferplus-8.onnx")
    emotion_out = os.path.join(models_dir, "emotion-ferplus-8_int8.onnx")
    quantize_onnx_model(emotion_in, emotion_out)
