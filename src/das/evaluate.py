import sklearn.metrics
import numpy as np
import pandas as pd
from typing import Optional, Dict, Callable, Any
import logging
from . import predict, data, utils, models, io
from .event_utils import evaluate_eventtimes


# to segment_utils
def evaluate_segments(labels_test,
                      labels_pred,
                      class_names,
                      confmat_as_pandas: bool = False,
                      report_as_dict: bool = False,
                      labels=None):
    """

    Args:
        labels_test (List): [nb_samples,]
        labels_pred (List): [nb_samples,]
        class_names ([type]): [description]
        confmat_as_pandas (bool, optional): [description]. Defaults to False.
        report_as_dict (bool, optional): [description]. Defaults to False.
        labels ([type], optional): [description]. Defaults to None.

    Returns:
        conf_mat
        report
    """

    # ensure labels_test and labels_pred have same length
    min_len = min(len(labels_test), len(labels_pred))
    labels_test = labels_test[:min_len]
    labels_pred = labels_pred[:min_len]

    conf_mat = sklearn.metrics.confusion_matrix(labels_test, labels_pred)
    if confmat_as_pandas:
        conf_mat = pd.DataFrame(data=conf_mat,
                                columns=['true ' + p for p in class_names],
                                index=['pred ' + p for p in class_names])
    if labels is None:
        labels = np.arange(len(class_names))
    report = sklearn.metrics.classification_report(labels_test,
                                                   labels_pred,
                                                   labels=labels,
                                                   target_names=class_names,
                                                   output_dict=report_as_dict,
                                                   digits=3)
    return conf_mat, report


def evaluate_segment_timing(segment_labels_true, segment_labels_pred, samplerate: float, event_tol: float):
    """[summary]

    Args:
        segment_labels_true ([type]): [description]
        segment_labels_pred ([type]): [description]
        samplerate ([type]): Hz [description]
        event_tol ([type]): seconds [description]

    Returns:
        [type]: [description]
    """
    segment_onsets_true, segment_offsets_true = segment_timing(segment_labels_true, samplerate)
    segment_onsets_pred, segment_offsets_pred = segment_timing(segment_labels_pred, samplerate)

    # ensure evaluate_eventtimes returns nearest_predicted_onsets (nearest true event for each predicted event),
    # if not, rename var
    segment_onsets_report, _, _, nearest_predicted_onsets = evaluate_eventtimes(segment_onsets_true, segment_onsets_pred,
                                                                                samplerate, event_tol)
    segment_offsets_report, _, _, nearest_predicted_offsets = evaluate_eventtimes(segment_offsets_true, segment_offsets_pred,
                                                                                  samplerate, event_tol)
    return segment_onsets_report, segment_offsets_report, nearest_predicted_onsets, nearest_predicted_offsets


# TODO: move to das.segment_utils
def segment_timing(labels, samplerate: float):
    """Get onset and offset time (in seconds) for each segment."""
    segment_onset_times = np.where(np.diff(labels) == 1)[0].astype(np.float) / samplerate  # explicit cast required?
    segment_offset_times = np.where(np.diff(labels) == -1)[0].astype(np.float) / samplerate
    return segment_onset_times, segment_offset_times


def evaluate_probabilities(x,
                           y,
                           model: Optional[models.keras.models.Model] = None,
                           params: Optional[Dict] = None,
                           model_savename: Optional[str] = None,
                           verbose: int = 1):
    """[summary]

    evaluate_probabilities(x, y, model=keras_model, params=params_dict)
    evaluate_probabilities(x, y, model_savename=save_string) -> will load model and params

    Args:
        x ([type]): [description]
        y ([type]): [description]
        model (Union[models.keras.models.Model], optional): [description]. Defaults to None.
        params (Union[Dict], optional): [description]. Defaults to None.
        model_savename (Union[str], optional): [description]. Defaults to None.
        verbose (int, optional): [description]. Defaults to 1.

    Returns:
        [type]: [description]
    """
    # TODO if called w/o x and y, load dataset from params
    if model is None or params is None:
        if model_savename is not None:
            model, params = utils.load_model_and_params(model_savename)
        else:
            raise ValueError(
                f'Required: Either a model and params OR a model_savename so we can load model and params. But model={model}, params={params}, model_savename={model_savename}.'
            )

    # do not prepend padding since we create y from the generator
    y_pred = predict.predict_probabilities(x, model=model, params=params, verbose=verbose, prepend_data_padding=False)

    eval_gen = data.AudioSequence(x, y, shuffle=False, **params)
    x, y = data.get_data_from_gen(eval_gen)

    return x, y, y_pred


def evaluate(savename: str, custom_objects: Optional[Dict[str, Callable]] = None, full_output: bool = True, verbose: int = 1):
    logging.info('Loading last best model.')
    model, params = utils.load_model_and_params(savename, custom_objects=custom_objects)
    logging.info(model.summary())

    logging.info(f"Loading data from {params['data_dir']}.")
    d = io.load(params['data_dir'], x_suffix=params['x_suffix'], y_suffix=params['y_suffix'])

    output: Dict[str, Any] = dict()
    if len(d['test']['x']) < params['nb_hist']:
        logging.info('No test data - skipping final evaluation step.')
        if full_output:
            return None, None, output
        else:
            return None, None
    else:
        logging.info('predicting')
        x_test, y_test, y_pred = evaluate_probabilities(x=d['test']['x'],
                                                        y=d['test']['y'],
                                                        model=model,
                                                        params=params,
                                                        verbose=verbose)

        labels_test = predict.labels_from_probabilities(y_test)
        labels_pred = predict.labels_from_probabilities(y_pred)

        logging.info('evaluating')
        conf_mat, report = evaluate_segments(labels_test, labels_pred, params['class_names'], report_as_dict=True)
        logging.info(conf_mat)
        logging.info(report)
        output['x_test'] = x_test
        output['y_test'] = y_test
        output['y_pred'] = y_pred
        output['labels_test'] = labels_test
        output['labels_pred'] = labels_pred
        if full_output:
            return conf_mat, report, output
        else:
            return conf_mat, report
