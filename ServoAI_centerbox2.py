import argparse
import time
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from utils import visualize
from picamera2 import Picamera2
import RPi.GPIO as GPIO
from time import sleep

# Global variables to calculate FPS
COUNTER, FPS = 0, 0
START_TIME = time.time()

# Initialize the camera
picam2 = Picamera2()
picam2.preview_configuration.main.size = (640, 480)
picam2.preview_configuration.main.format = "RGB888"
picam2.preview_configuration.align()
picam2.configure("preview")
picam2.start()

# Servo setup
servo_pin = 18  # GPIO pin connected to servo
GPIO.setmode(GPIO.BCM)
GPIO.setup(servo_pin, GPIO.OUT)

# LED setup
led_pin = 15  # GPIO pin connected to LED
GPIO.setup(led_pin, GPIO.OUT)
GPIO.output(led_pin, GPIO.LOW)  # Ensure LED is off initially

# Initialize PWM for servo (50Hz)
pwm = GPIO.PWM(servo_pin, 50)
pwm.start(0)

# Variables to track servo angle direction
servo_angle = 0
servo_direction = 1  # 1 for increasing, -1 for decreasing

def show_fps(image):
    """Function to display FPS on the image."""
    global COUNTER, FPS, START_TIME
    COUNTER += 1
    if (time.time() - START_TIME) > 1:
        FPS = COUNTER / (time.time() - START_TIME)
        COUNTER = 0
        START_TIME = time.time()
    
    fps_text = f'FPS = {FPS:.1f}'
    text_location = (10, 30)
    font_size = 1
    font_color = (255, 255, 255)  # White color
    font_thickness = 2
    cv2.putText(image, fps_text, text_location, cv2.FONT_HERSHEY_DUPLEX,
                font_size, font_color, font_thickness, cv2.LINE_AA)

def set_angle(angle):
    """Function to set the servo angle."""
    duty = angle / 18 + 2
    GPIO.output(servo_pin, True)
    pwm.ChangeDutyCycle(duty)
    sleep(0.5)
    GPIO.output(servo_pin, False)
    pwm.ChangeDutyCycle(0)

def move_servo_continuous():
    """Function to continuously move the servo between 0 and 180 degrees."""
    global servo_angle, servo_direction
    set_angle(servo_angle)
    servo_angle += 10 * servo_direction
    if servo_angle >= 180 or servo_angle <= 0:
        servo_direction *= -1

def move_servo_to_center(bbox_center_x, bbox_center_y, frame_center_x, frame_center_y):
    """Function to move the servo to center the detection box in the frame."""
    tolerance = 20  # Adjust this if needed
    if abs(bbox_center_x - frame_center_x) > tolerance:
        if bbox_center_x < frame_center_x:
            set_angle(servo_angle - 5)
            print("Moving to left")
        else:
            set_angle(servo_angle + 5)
            print("Moving to right")
    
    if abs(bbox_center_y - frame_center_y) > tolerance:
        if bbox_center_y < frame_center_y:
            set_angle(servo_angle + 5)
            print("Moving up")
        else:
            set_angle(servo_angle - 5)
            print("Moving down")

def run(model: str, max_results: int, score_threshold: float, 
        camera_id: int, width: int, height: int) -> None:
    
    frame_center_x = width // 2
    frame_center_y = height // 2
    detection_result_list = []
    detection_count = 0

    def save_result(result: vision.ObjectDetectorResult, unused_output_image: mp.Image, timestamp_ms: int):
        nonlocal detection_count
        detection_result_list.append(result)
        if len(result.detections) >= 2:
            detection_count += 1

    # Initialize the object detection model
    base_options = python.BaseOptions(model_asset_path=model)
    options = vision.ObjectDetectorOptions(base_options=base_options,
                                           running_mode=vision.RunningMode.LIVE_STREAM,
                                           max_results=max_results, score_threshold=score_threshold,
                                           result_callback=save_result)
    detector = vision.ObjectDetector.create_from_options(options)

    while True:
        im = picam2.capture_array()
        image = cv2.resize(im, (width, height))
        image = cv2.flip(image, -1)
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        detector.detect_async(mp_image, time.time_ns() // 1_000_000)

        # State 1: Servo moves continuously until 2 objects are detected
        if detection_count < 2:
            move_servo_continuous()
        else:
            # State 2: Adjust servo based on object detection
            if detection_result_list:
                current_frame = visualize(image, detection_result_list[0])
                for detection in detection_result_list[0].detections:
                    bbox = detection.bounding_box
                    bbox_center_x = bbox.origin_x + bbox.width // 2
                    bbox_center_y = bbox.origin_y + bbox.height // 2

                    # Move servo to center the detection box
                    move_servo_to_center(bbox_center_x, bbox_center_y, frame_center_x, frame_center_y)

                GPIO.output(led_pin, GPIO.HIGH)  # Turn on LED when detection is made
                detection_result_list.clear()
                print("Centered object")
            else:
                GPIO.output(led_pin, GPIO.LOW)  # Turn off LED when no detection

        # Show FPS on the frame
        show_fps(image)

        # Display the camera feed
        cv2.imshow('object_detection', image)
        
        if cv2.waitKey(1) == 27:  # Press ESC to exit
            break

    detector.close()
    pwm.stop()
    GPIO.cleanup()
    cv2.destroyAllWindows()

def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--model', help='Path of the object detection model.', default='best.tflite')
    parser.add_argument('--maxResults', help='Max number of detection results.', type=int, default=5)
    parser.add_argument('--scoreThreshold', help='The score threshold of detection results.', type=float, default=0.6)
    parser.add_argument('--cameraId', help='Id of camera.', type=int, default=0)
    parser.add_argument('--frameWidth', help='Width of frame to capture from camera.', type=int, default=640)
    parser.add_argument('--frameHeight', help='Height of frame to capture from camera.', type=int, default=480)
    args = parser.parse_args()

    run(args.model, args.maxResults, args.scoreThreshold, args.cameraId, args.frameWidth, args.frameHeight)

if __name__ == '__main__':
    main()
