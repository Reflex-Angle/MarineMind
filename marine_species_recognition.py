# -*- coding: utf-8 -*-
"""Marine_Species_Recognition.ipynb

Original file is located at
    https://colab.research.google.com/drive/1K8mKp66BzXzUqTl52hHASdf607O8UV9v
"""


"""**Download dataset**"""

# Commented out IPython magic to ensure Python compatibility.
!mkdir /var/colab/dataset
# %cd /var/colab/dataset
!curl -L -o archive.zip\
https://www.kaggle.com/api/v1/datasets/download/vencerlanz09/sea-animals-image-dataste
!unzip archive.zip
!rm archive.zip

"""**Import required modules**"""

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers
from sklearn.utils.class_weight import compute_class_weight

"""**Setup TPU**"""

try:
    resolver = tf.distribute.cluster_resolver.TPUClusterResolver()
    tf.config.experimental_connect_to_cluster(resolver)
    tf.tpu.experimental.initialize_tpu_system(resolver)
    strategy = tf.distribute.TPUStrategy(resolver)
    print("Running on TPU:", resolver.cluster_spec().as_dict())
except ValueError:
    strategy = tf.distribute.get_strategy()
print(f"Running on {strategy.num_replicas_in_sync} replicas")

"""**Augmentation**"""

# Define random data augmentation layers
augmentation_layers = [
    layers.RandomRotation(0.1),
    layers.RandomContrast(0.2),
    layers.RandomZoom(0.1),
    layers.RandomTranslation(0.1, 0.1),
    layers.RandomFlip("horizontal"),
]

# Function to apply augmentation
def data_augmentation(x):
    for layer in augmentation_layers:
        x = layer(x)
    return x

# Function to wrap data augmentation and label
@tf.autograph.experimental.do_not_convert
def augment_data(x, y):
    return data_augmentation(x), y

"""**Create datasets for training and validation**"""

dataset_dir = "/var/colab/dataset"

train_ds = tf.keras.preprocessing.image_dataset_from_directory(
    dataset_dir,
    validation_split=0.2,
    subset="training",
    seed=123,
    image_size=(224, 224),
    batch_size=128
)

validation_ds = tf.keras.preprocessing.image_dataset_from_directory(
    dataset_dir,
    validation_split=0.2,
    subset="validation",
    seed=123,
    image_size=(224, 224),
    batch_size=128
)

class_names = train_ds.class_names

# Apply augmentation to the training set
train_ds = train_ds.map(augment_data)

# Preprocess the dataset with ResNet preprocessing
preprocess_input = tf.keras.applications.resnet_v2.preprocess_input
train_ds = train_ds.map(lambda x, y: (preprocess_input(x), y))
validation_ds = validation_ds.map(lambda x, y: (preprocess_input(x), y))

# Prefetch for performance
train_ds = train_ds.prefetch(buffer_size=tf.data.AUTOTUNE)
validation_ds = validation_ds.prefetch(buffer_size=tf.data.AUTOTUNE)

print(f"Number of training samples: {train_ds.cardinality()}")
print(f"Number of validation samples: {validation_ds.cardinality()}")

"""**Save labels**"""

with open('labels.txt','w') as f:
    for label in class_names:
        f.write(f'{label}\n')

"""**Create Model**"""

# Create model within TPU strategy scope
with strategy.scope():
    inputs = tf.keras.Input(shape=(224, 224, 3))
    base_model = tf.keras.applications.ResNet50V2(
        weights="imagenet",
        input_shape=(224, 224, 3),
        include_top=False,
        pooling='max'
    )
    base_model.trainable = False
    for layer in base_model.layers[-20:]:
        layer.trainable = True

    x = base_model(inputs, training=False)
    x = layers.Dense(256, activation='relu')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.5)(x)

    x = layers.Dense(128, activation='relu')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.5)(x)
    outputs = layers.Dense(len(class_names), activation='softmax')(x)

    model = tf.keras.Model(inputs, outputs)

    model.compile(
        optimizer=tf.keras.optimizers.Adam(),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(),
        metrics=["accuracy"],
    )

"""**Model Summary**"""

model.summary(show_trainable=True)

# Access class names from the original training dataset before any transformations
train_ds_raw = tf.keras.preprocessing.image_dataset_from_directory(
    dataset_dir,
    validation_split=0.2,
    subset="training",
    seed=123,
    image_size=(224, 224),
    batch_size=128
)
class_names = train_ds_raw.class_names  # Get class names before transformations

# Extract labels by iterating through the original dataset
labels = np.concatenate([y for x, y in train_ds_raw], axis=0)

# Calculate class weights based on label distribution
from sklearn.utils.class_weight import compute_class_weight

class_weights = compute_class_weight('balanced', classes=np.unique(labels), y=labels)
class_weights = dict(enumerate(class_weights))

"""**Training**"""

epochs = 20
model.fit(
    train_ds,
    epochs=epochs,
    validation_data=validation_ds,
    class_weight=class_weights,
    callbacks=[
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=5, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss', factor=0.8, patience=3, mode='min'
        )
    ]
)

"""**Save the model**"""

model.save("model.keras")

"""**Test**"""

import tensorflow as tf
import numpy as np
from tensorflow.keras.preprocessing import image

class_names = []

with open('labels.txt','r') as f:
    for line in f:
        class_names.append(line.strip())

model = tf.keras.models.load_model('model.keras')

def preprocess_image(img_path):
    img = image.load_img(img_path, target_size=(224, 224))  # Resizing image to the input shape
    img_array = image.img_to_array(img)  # Convert the image to array
    img_array = np.expand_dims(img_array, axis=0)  # Add batch dimension
    img_array = tf.keras.applications.resnet_v2.preprocess_input(img_array)  # Preprocess for ResNet
    return img_array

def classify(img_path):
    input_image = preprocess_image(img_path)
    predictions = model.predict(input_image)
    predicted_class = np.argmax(predictions, axis=1)
    confidence = np.max(predictions, axis=1)
    print(f"Predicted class: {class_names[predicted_class[0]]}")
    print(f"Confidence: {confidence[0]:.2f}")

from PIL import Image
import IPython.display as display

#image of giant clam discovered by a diver taken at great depth with significant clarity loss
!wget 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQnTt4kKGSNkQ9gq47pXqAsFoIT2CthNR_YXfboQOoZCmHhDg8OcD-urc_4i95PqNgXkFo&usqp=CAU' -O test.jpg

img = Image.open('test.jpg')
display.display(img)

classify("test.jpg")