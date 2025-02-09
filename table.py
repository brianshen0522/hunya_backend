from PIL import Image
import numpy as np
import cv2
import os
from rapid_table_det.inference import TableDetector
from rapid_table_det.utils.visuallize import visuallize, extract_table_img

# Initialize the table detector once as a global variable
TABLE_DETECTOR = TableDetector()

def process_table(image_path):
    """
    Process an image to detect and extract tables.
    
    Args:
        image_path (str): Path to the input image file
        
    Returns:
        tuple: (table_image_path, no_table_image_path) if table is found,
               None if no table is detected
    """
    # Check if input image exists
    if not os.path.exists(image_path):
        print(f"Image file not found: {image_path}")
        return None
    
    # Detect tables using the global detector instance
    result, elapse = TABLE_DETECTOR(image_path)
    
    # If no table is detected, return None
    if len(result) == 0:
        print("No table detected.")
        return None

    # Load the image with PIL and convert to a numpy array (RGB)
    pil_img = Image.open(image_path).convert("RGB")
    img = np.array(pil_img)
    
    # Create a copy for later processing (to remove the table region)
    img_without_table = img.copy()
    
    # Get coordinates of the first detected table
    table_res = result[0]
    lt, rt, rb, lb = table_res["lt"], table_res["rt"], table_res["rb"], table_res["lb"]

    # Extract the Table Image using perspective transform
    table_img_np = extract_table_img(img.copy(), lt, rt, rb, lb)
    
    # Flip the table image vertically if it is a color image (3 channels)
    # if table_img_np.ndim == 3 and table_img_np.shape[2] == 3:
    #     table_img_np = cv2.flip(table_img_np, 1)  # flip horizontally
    #     table_img_np = cv2.flip(table_img_np, 0)  # flip vertically
    
    # --- Create a mask for the table region with a horizontal shrink ---
    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    
    # Define a margin (in pixels) to shrink the table region in the X direction.
    margin = 7.5  # adjust this value as needed

    # Adjust the left-side points (move to the right) and right-side points (move to the left)
    lt_shrunk = (lt[0] + margin, lt[1])
    lb_shrunk = (lb[0] + margin, lb[1])
    rt_shrunk = (rt[0] - margin, rt[1])
    rb_shrunk = (rb[0] - margin, rb[1])
    
    pts_shrunk = np.array([lt_shrunk, rt_shrunk, rb_shrunk, lb_shrunk], dtype=np.int32)
    cv2.fillPoly(mask, [pts_shrunk], 255)
    
    # Fill the table region with white in the "no table" image
    img_without_table[mask == 255] = [255, 255, 255]

    # Convert numpy arrays to PIL Images
    table_image = Image.fromarray(table_img_np)
    image_without_table = Image.fromarray(img_without_table)
    
    # Generate output paths in the same directory as input image
    base_dir = os.path.dirname(image_path)
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    
    table_path = os.path.join(base_dir, f"{base_name}_table.png")
    no_table_path = os.path.join(base_dir, f"{base_name}_no_table.png")
    
    # Save the images
    table_image.save(table_path)
    image_without_table.save(no_table_path)
    
    return table_path, no_table_path

def cleanup_images(*image_paths):
    """
    Delete the specified image files if they exist.
    
    Args:
        *image_paths: Variable number of image file paths to delete
    """
    for path in image_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Error deleting {path}: {str(e)}")

if __name__ == '__main__':
    image_file = "uploads/images/1.jpg"
    result = process_table(image_file)
    
    if result is None:
        print("Table not found.")
    else:
        table_img_path, no_table_img_path = result
        print(f"Table image saved to: {table_img_path}")
        print(f"Image without table saved to: {no_table_img_path}")
