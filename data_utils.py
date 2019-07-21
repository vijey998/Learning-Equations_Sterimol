"""
Handling of data related tasks, e.g. reading of input and generating data files.
    - *input_from_file* extracts input and output data from data file. Data file must contain a list of training,
    validation, extrapolation and metadata where metadata is a dictionary of the data parameters.
    - *input_penalty_epoch* generates new input data (using penalty boundaries) for penalty epochs. The output fed into
    the Estimator for these epochs is set to zero because in penalty epochs we compute gradients based only on the
    output calculated by the EQL, not the expected output (no MSE or similar is calculated).
    - *files_from_fn* generates a data file containing training-, validation-, extrapolation- and metadata for a fn
    passed through the input in parameter dictionary. The python function has to be defined in data_utils.py.
   *files_from_fn* is also called when *data_utils.py* is run from command line with the parameter dictionary passed as
   a string.
"""
import gzip
import os.path
import pickle
from ast import literal_eval
from sys import argv

import numpy as np
import tensorflow as tf

from utils import to_float32, number_of_positional_arguments

"""Equation 1-4 from the paper. Equation 5 describes the cart pendulum from the paper."""


def F1(x1, x2, x3, x4):
    """Requires 1 hidden layer."""
    y0 = (np.sin(np.pi * x1) + np.sin(2 * np.pi * x2 + np.pi / 8.0) + x2 - x3 * x4) / 3.0
    return y0,


def F2(x1, x2, x3, x4):
    """Requires 2 hidden layers."""
    y0 = (np.sin(np.pi * x1) + x2 * np.cos(2 * np.pi * x1 + np.pi / 4.0) + x3 - x4 * x4) / 3.0
    return y0,


def F3(x1, x2, x3, x4):
    """Requires 2 hidden layers."""
    y0 = ((1.0 + x2) * np.sin(np.pi * x1) + x2 * x3 * x4) / 3.0
    return y0,


def F4(x1, x2, x3, x4):
    """Requires 4 hidden layers."""
    y0 = 0.5 * (np.sin(np.pi * x1) + np.cos(2.0 * x2 * np.sin(np.pi * x1)) + x2 * x3 * x4)
    return y0,


def F5(x1, x2, x3, x4):
    """Equation for cart pendulum. Requires 4 hidden layers."""
    y1 = x3
    y2 = x4
    y3 = (-x1 - 0.01 * x3 + x4 ** 2 * np.sin(x2) + 0.1 * x4 * np.cos(x2) + 9.81 * np.sin(x2) * np.cos(x2)) \
         / (np.sin(x2) ** 2 + 1)
    y4 = -0.2 * x4 - 19.62 * np.sin(x2) + x1 * np.cos(x2) + 0.01 * x3 * np.cos(x2) - x4 ** 2 * np.sin(x2) * np.cos(x2) \
         / (np.sin(x2) ** 2 + 1)
    return y1, y2, y3, y4,

def F6(x1,x2,x3,x4,x5):
    #y0= (np.log10(np.absolute(x1 + 2*np.sin(x2*x3*x4))+0.000000001) -             np.cos(np.exp(x5)/np.log10(np.absolute(x1)+0.000000001))/(x2*x3*np.sin(x4**2)))/(3.0*(0.01+np.cos(x5)**2))
    y0=np.log10(np.absolute(x1 + 2*np.sin(x2*x3))+0.000000001)/(np.exp(x4)/3.0 - np.cos(x5)*x1)
    return y0,


data_gen_params = {'file_name': 'S1data',  # file name for the generated data file, will be created in data/
                   'fn_to_learn': 'F2',  # python function to learn, should be defined in data_utils
                   'train_val_examples': 10000,  # total number of examples for training and validation
                   'train_val_bounds': (-1.0,1.0),  # domain boundaries for validation and training normal epochs
                   'test_examples': 5000,  # number of test examples, if set to None no test_data file is created
                   'test_bounds': (-2.0,2.0),  # domain boundaries for test data
                   'noise': 0.0,
                   'seed': None
                   }


def generate_data(tort,fn, num_examples, bounds, noise, seed=None):
    """
    np.random.seed(seed)
    lower, upper = bounds
    input_dim = number_of_positional_arguments(fn)
    xs = np.random.uniform(lower, upper, (num_examples, input_dim)).astype(np.float32)
    xs_as_list = np.split(xs, input_dim, axis=1)
    ys = fn(*xs_as_list)
    ys = np.concatenate(ys, axis=1)
    ys += np.random.uniform(-noise, noise, ys.shape)
    """
    if tort==0:
        xs=X_test
        ys=y_test
    else:
        xs=X_train
        ys=y_train
    return xs, ys


def data_from_file(filename, split=None):
    """
    Routine extracting data from given file.
    :param filename: path to the file data should be extracted from
    :param split: if split is not None, the data is split into two chunks, one of size split*num_examples and one of
                  size (1-split)*num_examples. If it is None, all data is returned as one chunk
    :return: if split is not None list of data-chunks, otherwise all data as one chunk
    """
    data = to_float32(pickle.load(gzip.open(filename, "rb"), encoding='latin1'))
    if split is not None:
        split_point = int(len(data[0]) * split)
        data = [np.split(dat, [split_point]) for dat in data]
        data = zip(*data)
    return data


def input_from_data(data, batch_size, repeats):
    """
    Function turning data into input for the network. Provides enough data for *repeats* epochs.
    :param data: numpy array of data
    :param batch_size: size of batch returned, only relevant for training regime
    :param repeats: integer factor determining how many times (epochs) data is reused
    :return: *repeats* times data split into inputs and labels in batches
    """
    ds = tf.data.Dataset.from_tensor_slices(data).shuffle(buffer_size=1000).repeat(repeats).batch(batch_size)
    xs, ys = ds.make_one_shot_iterator().get_next()
    return xs, ys


def get_penalty_data(num_examples, penalty_bounds, num_inputs, num_outputs):
    """
    Function returning penalty data. In penalty epoch labels are irrelevant, therefore labels are set to zero.
    Only provides enough data to train for one epoch.
    :param num_examples: Total number of examples to be trained in penalty epoch.
    :param penalty_bounds: Boundaries to be used to generate penalty data, either a tuple or a list of tuples
    """
    if isinstance(penalty_bounds, tuple):
        lower, upper = penalty_bounds
    else:
        lower, upper = zip(*penalty_bounds)
    xs = np.random.uniform(lower, upper, (num_examples, num_inputs)).astype(np.float32)
    ys = np.zeros((num_examples, num_outputs), dtype=np.float32)
    return xs, ys


def get_input_fns(train_val_split, batch_size, train_val_file, test_file, penalty_every, num_inputs, num_outputs,
                  train_val_examples, penalty_bounds, extracted_penalty_bounds, **_):
    """
    Routine to determine which input function to use for training(normal or penalty epoch) / validation / testing.
    :param train_val_split: float specifying the data split, .8 means 80% of data is used for training, 20% for val
    :param batch_size: Size of batches used for training (both in normal and penalty epochs).
    :param train_val_file: Path to file containing training and validation data.
    :param test_file: Path to file containing test data.
    :param penalty_every: Integer specifying after how many normal epochs a penalty epoch occurs.
    :param num_inputs: number of input arguments
    :param num_outputs: number of outputs
    :param train_val_examples: number of examples to use for training and validation
    :param penalty_bounds: default domain boundaries used to generate penalty epoch training data.
    :param extracted_penalty_bounds: domain boundaries for penalty data generation extracted from data files
    :return: functions returning train-, penalty_train-, validation- and (if provided in datafile) test-input
             if no extrapolation test data is provided test_input is None
    """
    penalty_bounds = penalty_bounds or extracted_penalty_bounds
    train_data, val_data = data_from_file(train_val_file, split=train_val_split)
    penalty_data = get_penalty_data(num_examples=int(train_val_split * train_val_examples),
                                    penalty_bounds=penalty_bounds, num_inputs=num_inputs, num_outputs=num_outputs)
    train_input = lambda: input_from_data(data=train_data, batch_size=batch_size, repeats=penalty_every)
    val_input = lambda: input_from_data(data=val_data, batch_size=batch_size, repeats=1)
    penalty_input = lambda: input_from_data(data=penalty_data, batch_size=batch_size, repeats=1)
    if test_file is not None:
        test_data = data_from_file(test_file)
        test_input = lambda: input_from_data(data=test_data, batch_size=batch_size, repeats=1)
    else:
        test_input = None
    return train_input, penalty_input, val_input, test_input


def extract_metadata(train_val_file, test_file, domain_bound_factor=2, res_bound_factor=10):
    """
    Routine to extract additional information about data from data file.
    :param train_val_file: Path to training/validation data file
    :param test_file: Path to extrapolation data file
    :param domain_bound_factor: factor to scale the domain boundary of train/val data to get penalty data boundary
    :param res_bound_factor: factor to scale the maximum output of train/val data to get penalty data result boundary
    :return: metadata dict
    """
    train_val_data = pickle.load(gzip.open(train_val_file, "rb"), encoding='latin1')
    train_val_examples = train_val_data[0].shape[0]
    num_inputs = train_val_data[0].shape[1]
    num_outputs = train_val_data[1].shape[1]
    extracted_output_bound = np.max(np.abs(train_val_data[1])) * res_bound_factor
    if test_file is not None:
        test_data = pickle.load(gzip.open(test_file, "rb"), encoding='latin1')
        extracted_penalty_bounds = zip(np.min(test_data[0], axis=0), np.max(test_data[0], axis=0))
    else:
        extracted_penalty_bounds = zip(np.min(train_val_data[0], axis=0) * domain_bound_factor,
                                       np.max(train_val_data[0], axis=0) * domain_bound_factor)
    metadata = dict(train_val_examples=train_val_examples, num_inputs=num_inputs, num_outputs=num_outputs,
                    extracted_output_bound=extracted_output_bound, extracted_penalty_bounds=extracted_penalty_bounds)
    return metadata


def files_from_fn(file_name, fn_to_learn, train_val_examples, test_examples, train_val_bounds,
                  test_bounds, noise, seed=None):
    """
    Routine generating .gz file with train-, validation, test and meta-data from function.
    It is worth noting that that the function is saved as a string in metadata.
    :param file_name: Name of the data file to be created. It is being saved in the directory 'data'.
    :param fn_to_learn: string name of python function used to generate data. Should be defined in data_utils.py.
    :param train_val_examples: Total number of examples used for training and validation.
    :param train_val_bounds: Boundaries used to generate training and validation data.
    :param test_examples: Total number of examples used for testing.
    :param test_bounds: Boundaries used to generate test data.
    """
    fn_to_learn = globals()[fn_to_learn]
    if not os.path.exists('data'):
        os.mkdir('data')
    train_val_set = generate_data(fn=fn_to_learn, num_examples=train_val_examples, bounds=train_val_bounds, noise=noise,
                                  seed=seed,tort=1)
    #print(train_val_set)
    train_val_data_file = os.path.join('data', file_name + '_train_val')
    pickle.dump(train_val_set, gzip.open(train_val_data_file, "wb"))
    print('Successfully created train/val data file in %s.' % train_val_data_file)

    if test_examples is not None:
        test_set = generate_data(fn=fn_to_learn, num_examples=test_examples, bounds=test_bounds, noise=noise, seed=seed,tort=0)
        #print(test_set)
        test_data_file = os.path.join('data', file_name + '_test')
        pickle.dump(test_set, gzip.open(test_data_file, "wb"))
        print('Successfully created test data file in %s.' % test_data_file)
    


if __name__ == '__main__':
    if len(argv) > 1:
        print('Updating default parameters.')
        data_gen_params.update(literal_eval(argv[1]))
    else:
        print('Using default parameters.')
    """
    import pickle
    import gzip
    with gzip.open('H:\\JupyterGod\\EQL_Tensorflow-master\\EQL_Tensorflow-master\\data\\F99_6data', 'rb') as filehandle:  
        X = pickle.load(filehandle)
    print(X.shape)
    
    #for k in range (0,9):
     #   X[:,k*4+1:k*4+4]*=10
    import pandas as pd
    df=pd.read_csv('gdb9.csv')
    import numpy as np
    with open("missing", "rb") as fp:
        missing = pickle.load(fp)
    #df=df.drop(np.array(missing)-1,axis=0)
    print(df.shape)
    y=np.array(df.iloc[:,1:4])
    print(y.shape)
    #y=1./(y+1e-10)
    #y=y[:,0]
    #X=np.delete(X,[1,5,9,13,17,21,25,29,33],axis=0)
    #print(X.shape," new")
    #print(y.shape)
    #y=np.reciprocal(y+0.00001)
    #y*=10
    """
    xin1=np.array([[3,1.52,2.04],
    [4.11,1.52,3.17],
    [4.11,1.9,3.17],
    [6.17,1.52,4.54],
    [6.17,1.9,3.49],
    [5.05,1.52,3.49],
    [6.17,3.16,3.49],
    [4.11,2.76,3.17]]
    )
    yin1=np.array([[31.032,31.136],
     [40.24,40.24 ],
     [49.848, 49.848],
     [59.016 ,59.536],
     [66.936 ,67.064],
     [50.12  ,53.096],
     [79.52  ,85.232],
     [56.72  ,56.688]])


    xin=np.array([[4.41,1,2.94],
    [4.85,1.16,3.75],
    [4.99,1.69,3.84],
    [4.74,1.93,3.09],
    [5.15,1.93,4.42],
    [5.67,1.91,4.35],
    [4.78,1.36,4.17],
    [4.79,1.9,4.18],
    [6.13,2.39,4.18]])#z

    yin=np.array([[ 61.352  ,61.384],
     [ 79.912  ,79.928],
     [ 94.072 , 93.992],
     [ 80.28   ,77.376],
     [ 92.536 , 92.624],
     [109.176 ,109.176],
     [ 94.408  ,94.416],
     [109.376 ,109.368],
     [123.84  ,123.768]])
    xin=(np.vstack([xin1,xin]))
    yin=(np.vstack([yin1[:,1].reshape(8,1),yin[:,1].reshape(9,1)]))
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(xin,yin, test_size=0.20, random_state=42)
    
    files_from_fn(**data_gen_params)
