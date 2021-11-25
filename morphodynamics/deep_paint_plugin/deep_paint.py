from napari_plugin_engine import napari_hook_implementation
from qtpy.QtWidgets import (QWidget, QPushButton,
QVBoxLayout, QLabel, QComboBox,QFileDialog)

from joblib import dump, load
from pathlib import Path
import numpy as np
import pandas as pd
import torchvision.models as models
from torch import nn

from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

from .deep_paint_utils import filter_image, predict_image
from ..napari_plugin.VHGroup import VHGroup
from ..parameters import Param

class DeepPaintWidget(QWidget):
    """
    Implementation of a napari widget for interactive segmentation performed
    via a random forest model trained on annotations. The filters used to 
    generate the model features are taken from the first layer of a VGG16 model
    as proposed here: https://github.com/hinderling/napari_pixel_classifier

    Parameters
    ----------
    napari_viewer: napari.Viewer
        main napari viwer
    param: morphodymamics.Param
        parameter object with infos on dataset
    """
    
    def __init__(self, napari_viewer, param=None, parent=None):
        super().__init__(parent=parent)
        self.viewer = napari_viewer
        
        self.param = param
        if self.param is None:
            self.param = Param()
        
        self.scalings = [1,2]
        self.model = None
        self.random_forest = None

        self._layout = QVBoxLayout()
        self.setLayout(self._layout)

        self.select_layer_widget = QComboBox()
        self.select_layer_widget.addItems([x.name for x in self.viewer.layers])
        self._layout.addWidget(self.select_layer_widget)
        self.select_layer_widget.currentIndexChanged.connect(self.select_layer)

        self.settings_vgroup = VHGroup('Settings', orientation='G')
        self._layout.addWidget(self.settings_vgroup.gbox)

        self.num_scales_combo = QComboBox()
        self.num_scales_combo.addItems(['[1]', '[1,2]', '[1,2,4]'])
        self.num_scales_combo.setCurrentText('[1,2]')
        self.num_scales_combo.currentIndexChanged.connect(self.update_scalings)
        self.settings_vgroup.glayout.addWidget(QLabel('Number of scales'), 0, 0)
        self.settings_vgroup.glayout.addWidget(self.num_scales_combo, 0, 1)

        self.add_layers_btn = QPushButton('Add annotation/predict layers')
        self.add_layers_btn.clicked.connect(self.add_annotation_layer)
        self._layout.addWidget(self.add_layers_btn)

        self.update_model_btn = QPushButton('Update model')
        self.update_model_btn.clicked.connect(self.update_model)
        self._layout.addWidget(self.update_model_btn)

        self.prediction_btn = QPushButton('Predict single frame')
        self.prediction_btn.clicked.connect(self.predict)
        self._layout.addWidget(self.prediction_btn)

        self.prediction_all_btn = QPushButton('Predict all frames')
        self.prediction_all_btn.clicked.connect(self.predict_all)
        self._layout.addWidget(self.prediction_all_btn)

        self.save_model_btn = QPushButton('Save trained model')
        self.save_model_btn.clicked.connect(self.save_model)
        self._layout.addWidget(self.save_model_btn)

        self.load_model_btn = QPushButton('Load trained model')
        self.load_model_btn.clicked.connect(self.load_model)
        self._layout.addWidget(self.load_model_btn)

        self.viewer.events.layers_change.connect(self.update_layer_list)

    def update_layer_list(self, event):
        
        keep_channel = self.param.morpho_name
        self.select_layer_widget.clear()
        self.select_layer_widget.addItems([x.name for x in self.viewer.layers])
        if keep_channel in [x.name for x in self.viewer.layers]:
            self.select_layer_widget.setCurrentText(keep_channel)

    def select_layer(self):

        self.param.morpho_name = self.select_layer_widget.currentText()

    def add_annotation_layer(self):

        self.viewer.add_labels(
            data=np.zeros((self.viewer.layers[self.param.morpho_name].data.shape), dtype=np.uint8),
            name='annotations'
            )
        self.viewer.add_labels(
            data=np.zeros((self.viewer.layers[self.param.morpho_name].data.shape), dtype=np.uint8),
            name='prediction'
            )

    def update_scalings(self):

        self.scalings = eval(self.num_scales_combo.currentText())
        self.param.scalings = self.scalings
        
    def update_model(self):
        """Given a set of new annotations, update the random forest model."""

        if self.model is None:
            self._load_nn_model()
       
        n_features = 64

        non_empty = np.unique(np.where(self.viewer.layers['annotations'].data > 0)[0])
        if len(non_empty) == 0:
            raise Exception('No annotations found')

        all_values = []
        for ind, t in enumerate(non_empty):
            image = self.viewer.layers[self.param.morpho_name].data[t]

            full_annotation = np.ones((n_features, image.shape[0], image.shape[1]),dtype=np.bool8)
            full_annotation = full_annotation * self.viewer.layers['annotations'].data[t,:,:]>0

            all_scales = filter_image(image, self.model, self.scalings)
            all_values_scales=[]
            for a in all_scales:
                extract = a[0, full_annotation]
                all_values_scales.append(np.reshape(extract, (n_features, int(extract.shape[0]/n_features))).T)
            all_values.append(np.concatenate(all_values_scales, axis=1))

        all_values = np.concatenate(all_values,axis=0)
        features = pd.DataFrame(all_values)
        target_im = self.viewer.layers['annotations'].data[self.viewer.layers['annotations'].data>0]
        targets = pd.Series(target_im)

        # train model
        #split train/test
        X, X_test, y, y_test = train_test_split(features, targets, 
                                            test_size = 0.2, 
                                            random_state = 42)

        #train a random forest classififer
        self.random_forest = RandomForestClassifier(n_estimators=100)
        self.random_forest.fit(X, y)

    def predict(self):
        """Predict the segmentation of the currently viewed frame based 
        on a RF model trained with annotations"""

        if self.model is None:
            self._load_nn_model()
        if self.random_forest is None:
            self.update_model()

        self.check_prediction_layer_exists()
        step = self.viewer.dims.current_step[0]

        image = self.viewer.layers[self.param.morpho_name].data[step]
        predicted_image = predict_image(image, self.model, self.random_forest)
        self.viewer.layers['prediction'].data[step] = predicted_image
        self.viewer.layers['prediction'].refresh()

    def predict_all(self):
        """Predict the segmentation of all frames based 
        on a RF model trained with annotations"""

        if self.model is None:
            self._load_nn_model()

        self.check_prediction_layer_exists()

        for step in range(self.viewer.dims.nsteps[0]):
            image = self.viewer.layers[self.param.morpho_name].data[step]
            predicted_image = predict_image(image, self.model, self.random_forest)
            self.viewer.layers['prediction'].data[step] = predicted_image

    def check_prediction_layer_exists(self):

        layer_names = [x.name for x in self.viewer.layers]
        if 'prediction' not in layer_names:
            self.viewer.add_labels(
                data=np.zeros((self.viewer.layers[self.param.morpho_name].data.shape), dtype=np.uint8),
                name='prediction'
                )

    def save_model(self):
        """Select file where to save the classifier model."""

        dialog = QFileDialog()
        save_file, _ = dialog.getSaveFileName(self, "Save model", None, "JOBLIB (*.joblib)")
        save_file = Path(save_file)
        dump(self.random_forest, save_file)
        self.param.random_forest = save_file#.as_posix()

    def load_model(self):
        """Select classifier model file to load."""

        dialog = QFileDialog()
        save_file, _ = dialog.getOpenFileName(self, "choose model", None, "JOBLIB (*.joblib)")
        save_file = Path(save_file)
        self.random_forest = load(save_file)
        self.param.random_forest = save_file#.as_posix()

    def _load_nn_model(self):
        """Load VGG16 model from torchvision"""

        vgg16 = models.vgg16(pretrained=True)
        self.model = nn.Sequential(vgg16.features[0])