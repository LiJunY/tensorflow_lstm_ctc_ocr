#!/usr/bin/env python
# encoding=utf-8
# Compatibility imports
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time

import tensorflow as tf
import scipy.io.wavfile as wav
import numpy as np

import common
from common import unzip, read_data_for_lstm_ctc

try:
    from python_speech_features import mfcc
except ImportError:
    print("Failed to import python_speech_features.\n Try pip install python_speech_features.")
    raise ImportError

from utils import maybe_download as maybe_download
from utils import sparse_tuple_from as sparse_tuple_from

SPACE_INDEX = 0
FIRST_INDEX = ord('0') - 1  # 0 is reserved to space

# Some configs
num_features = 64
# Accounting the 0th indice +  space + blank label = 28 characters
num_classes = ord('9') - ord('0') + 1 + 1 + 1
print(num_classes)
# Hyper-parameters
num_epochs = 1000
num_hidden = 64
num_layers = 1
batch_size = 1
initial_learning_rate = 0.0001
momentum = 0.9

num_examples = 1
num_batches_per_epoch = int(num_examples / batch_size)

# Loading the data

audio_filename = maybe_download('LDC93S1.wav', 93638)
target_filename = maybe_download('LDC93S1.txt', 62)

fs, audio = wav.read(audio_filename)
"""
inputs = mfcc(audio, samplerate=fs)

# Tranform in 3D array
train_inputs = np.asarray(inputs[np.newaxis, :])  # the shape of train_inputs is (1,291,13)
print(train_inputs.shape)
train_inputs = (train_inputs - np.mean(train_inputs)) / np.std(train_inputs)
print(train_inputs.shape)
train_seq_len = [train_inputs.shape[1]]  # 291

# Readings targets
with open(target_filename, 'rb') as f:
    for line in f.readlines():
        if line[0] == ';':
            continue

        # Get only the words between [a-z] and replace period for none
        original = ' '.join(line.strip().lower().split(' ')[2:]).replace('.', '')
        targets = original.replace(' ', '  ')
        targets = targets.split(' ')
print(
    targets)  # ['she', '', 'had', '', 'your', '', 'dark', '', 'suit', '', 'in', '', 'greasy', '', 'wash', '', 'water', '', 'all', '', 'year']
# Adding blank label
targets = np.hstack([common.SPACE_TOKEN if x == '' else list(x) for x in targets])
print(targets)
# Transform char into index
targets = np.asarray([SPACE_INDEX if x == common.SPACE_TOKEN else ord(x) - FIRST_INDEX
                      for x in targets])
"""
test_input, test_codes = unzip(list(read_data_for_lstm_ctc("test/*.png"))[:common.BATCH_SIZE])
test_input = test_input.swapaxes(1, 2)
train_inputs = test_input
print("targets", test_codes)
targets = np.asarray([SPACE_INDEX if x == common.SPACE_TOKEN else (ord(x) - FIRST_INDEX) for x in test_codes[0]])
print(test_input.shape)
print("targets", targets)
print("train_inputs.shape[1]", train_inputs.shape[1])
# Creating sparse representation to feed the placeholder
train_targets = sparse_tuple_from([targets])
print(train_targets)
train_seq_len = [train_inputs.shape[1]]  # 200
# We don't have a validation dataset :(
val_inputs, val_targets, val_seq_len = train_inputs, train_targets, train_seq_len

# THE MAIN CODE!

graph = tf.Graph()
with graph.as_default():
    # e.g: log filter bank or MFCC features
    # Has size [batch_size, max_stepsize, num_features], but the
    # batch_size and max_stepsize can vary along each step
    inputs = tf.placeholder(tf.float32, [None, None, num_features])

    # Here we use sparse_placeholder that will generate a
    # SparseTensor required by ctc_loss op.
    targets = tf.sparse_placeholder(tf.int32)

    # 1d array of size [batch_size]
    seq_len = tf.placeholder(tf.int32, [None])

    # Defining the cell
    # Can be:
    #   tf.nn.rnn_cell.RNNCell
    #   tf.nn.rnn_cell.GRUCell
    cell = tf.nn.rnn_cell.LSTMCell(num_hidden, state_is_tuple=True)

    # Stacking rnn cells
    stack = tf.nn.rnn_cell.MultiRNNCell([cell] * num_layers,
                                        state_is_tuple=True)

    # The second output is the last state and we will no use that
    outputs, _ = tf.nn.dynamic_rnn(cell, inputs, seq_len, dtype=tf.float32)

    shape = tf.shape(inputs)
    batch_s, max_timesteps = shape[0], shape[1]

    # Reshaping to apply the same weights over the timesteps
    outputs = tf.reshape(outputs, [-1, num_hidden])

    # Truncated normal with mean 0 and stdev=0.1
    # Tip: Try another initialization
    # see https://www.tensorflow.org/versions/r0.9/api_docs/python/contrib.layers.html#initializers
    W = tf.Variable(tf.truncated_normal([num_hidden,
                                         num_classes],
                                        stddev=0.1))
    # Zero initialization
    # Tip: Is tf.zeros_initializer the same?
    b = tf.Variable(tf.constant(0., shape=[num_classes]))

    # Doing the affine projection
    logits = tf.matmul(outputs, W) + b

    # Reshaping back to the original shape
    logits = tf.reshape(logits, [batch_s, -1, num_classes])

    # Time major
    logits = tf.transpose(logits, (1, 0, 2))

    loss = tf.contrib.ctc.ctc_loss(logits, targets, seq_len)
    cost = tf.reduce_mean(loss)

    optimizer = tf.train.MomentumOptimizer(initial_learning_rate,
                                           0.9).minimize(cost)

    # Option 2: tf.contrib.ctc.ctc_beam_search_decoder
    # (it's slower but you'll get better results)
    decoded, log_prob = tf.contrib.ctc.ctc_greedy_decoder(logits, seq_len)

    # Accuracy: label error rate
    acc = tf.reduce_mean(tf.edit_distance(tf.cast(decoded[0], tf.int32),
                                          targets))

with tf.Session(graph=graph) as session:
    # Initializate the weights and biases
    tf.initialize_all_variables().run()

    for curr_epoch in xrange(num_epochs):
        train_cost = train_ler = 0
        start = time.time()

        for batch in xrange(num_batches_per_epoch):
            feed = {inputs: train_inputs,
                    targets: train_targets,
                    seq_len: train_seq_len}

            batch_cost, _ = session.run([cost, optimizer], feed)
            train_cost += batch_cost * batch_size
            train_ler += session.run(acc, feed_dict=feed) * batch_size

        train_cost /= num_examples
        train_ler /= num_examples

        val_feed = {inputs: val_inputs,
                    targets: val_targets,
                    seq_len: val_seq_len}

        val_cost, val_ler = session.run([cost, acc], feed_dict=val_feed)

        log = "Epoch {}/{}, train_cost = {:.3f}, train_ler = {:.3f}, val_cost = {:.3f}, val_ler = {:.3f}, time = {:.3f}"
        print(log.format(curr_epoch + 1, num_epochs, train_cost, train_ler,
                         val_cost, val_ler, time.time() - start))
    # Decoding
    d = session.run(decoded[0], feed_dict=feed)
    str_decoded = ''.join([chr(x) for x in np.asarray(d[1]) + FIRST_INDEX])
    # Replacing blank label to none
    str_decoded = str_decoded.replace(chr(ord('9') + 1), '')
    # Replacing space label to space
    str_decoded = str_decoded.replace(chr(ord('0') - 1), ' ')

    #print('Original:\n%s' % original)
    print('Decoded:\n%s' % str_decoded)
