import json
import os
import time
from pathlib import Path
from typing import List, Dict

import jieba
import numpy as np
import pandas as pd
from keras.layers import Input, LSTM, Dense, \
    Embedding, Bidirectional, Concatenate, Flatten, RepeatVector, \
    Activation, Permute, Multiply
from keras.models import Model, load_model
from keras.preprocessing.text import Tokenizer
from keras_preprocessing.sequence import pad_sequences
from numpy import ndarray


def padding_sign(padded_seq: ndarray, dict_size: int, mode: bool) -> ndarray:
    sign: List[List[int]] = []
    # decoder_input添加SOS
    if mode:
        for i in padded_seq:
            sign.append([dict_size + 1])
        ndarray_sign: ndarray = np.array(sign)
        arr = np.concatenate([ndarray_sign, padded_seq], axis=-1)
    # decoder_target添加EOS
    else:
        for i in padded_seq:
            i.append(dict_size + 2)
        arr = padded_seq
    return arr


class DataInitialize:
    data_path: os.PathLike[str]
    input_str: List[str]
    output_str: List[str]
    input_cut: List[List[str]]
    output_cut: List[List[str]]
    input_vec: List[List[str]]
    output_vec: List[List[str]]
    dict: Dict[str, int]

    def __init__(self, data_path_class: os.PathLike[str], dict_path_class: os.PathLike[str]):
        self.data_path = data_path_class
        jieba.load_userdict(dict_path_class)

    # 导入excel内容，并作为列表分别输出output和input
    def load_data(self):
        df = pd.read_excel(data_path)
        self.input_str = df['input'].tolist()
        self.output_str = df['output'].tolist()

    # 传入句子 传出分词后的列表
    @classmethod
    def jieba_cut(cls, sequences: List[str]) -> List[List[str]]:
        return [list(jieba.cut(text)) for text in sequences]

    # 用jieba进行分词，使用tensorflow转换为向量
    def word_to_vec(self):
        self.input_cut = self.jieba_cut(self.input_str)
        self.output_cut = self.jieba_cut(self.output_str)
        tokenizer = Tokenizer()
        tokenizer.fit_on_texts(self.input_cut + self.output_cut)
        self.dict = tokenizer.word_index
        self.input_vec = tokenizer.texts_to_sequences(self.input_cut)
        self.output_vec = tokenizer.texts_to_sequences(self.output_cut)


# noinspection PyTypeChecker
def train_model(batch_size: int, epochs: int):
    print(f"{time.asctime()} 正在处理训练数据...")
    encoder_input_data = np.load(encoder_input)
    decoder_input_data = np.load(decoder_input)
    decoder_target_data = np.load(decoder_output)
    print(f"{time.asctime()} 循环轮数:{epochs} batch size:{batch_size}")
    model = load_model(model_path)
    model.fit([encoder_input_data, decoder_input_data], decoder_target_data,
              batch_size=batch_size,
              epochs=epochs)
    model.save(model_path)


def get_dict() -> Dict[str]:
    with open(dict_path, 'r', encoding='utf-8') as file:
        emb_dict = json.load(file)
    return emb_dict


# 构建训练模型
def setup_model():
    emb_dict = get_dict()
    # 包括了EOS SOS的长度
    vocabulary_size = len(emb_dict) + 3
    embedding_dim = int(pow(vocabulary_size, 1.0 / 4))
    latent_dim = embedding_dim * 40

    print(f"{time.asctime()} 词典长度为：{len(emb_dict)}")
    print(f"{time.asctime()} 拓展后长度为：{vocabulary_size}")
    # 设置encoder
    # 设置embeddings层
    print(f"{time.asctime()} 构建训练模型...")
    encoder_inputs = Input(shape=(None,), name='encoder_input')
    encoder_embedding = Embedding(vocabulary_size,
                                  embedding_dim,
                                  mask_zero=True,
                                  name='encoder_Embedding')(encoder_inputs)
    encoder = Bidirectional(LSTM(latent_dim, return_sequences=True, return_state=True, dropout=0.5),
                            name='encoder_BiLSTM')
    encoder_outputs, fw_state_h, fw_state_c, bw_state_h, bw_state_c = encoder(encoder_embedding)
    state_h = Concatenate(axis=-1, name='encoder_state_h')([fw_state_h, bw_state_h])
    state_c = Concatenate(axis=-1, name='encoder_state_c')([fw_state_c, bw_state_c])
    encoder_states = [state_h, state_c]

    # 设置decoder
    decoder_inputs = Input(shape=(None,), name='decoder_input')
    decoder_embedding = Embedding(vocabulary_size,
                                  embedding_dim,
                                  mask_zero=True,
                                  name='decoder_embedding')(decoder_inputs)
    decoder_lstm = LSTM(latent_dim * 2,
                        return_sequences=True,
                        return_state=True,
                        name='decoder_LSTM',
                        dropout=0.5)
    decoder_outputs, _, _ = decoder_lstm(decoder_embedding,
                                         initial_state=encoder_states)

    # attention层
    attention = Dense(1, activation='tanh')(encoder_outputs)
    attention = Flatten()(attention)
    attention = Activation('softmax')(attention)
    attention = RepeatVector(latent_dim * 2)(attention)
    attention = Permute([2, 1])(attention)
    sent_dense = Multiply()([decoder_outputs, attention])

    # Dense层
    decoder_dense = Dense(vocabulary_size, activation='softmax', name='dense_layer')
    decoder_outputs = decoder_dense(sent_dense)
    model = Model([encoder_inputs, decoder_inputs], decoder_outputs)
    model.compile(optimizer='rmsprop', loss='sparse_categorical_crossentropy',
                  metrics=['accuracy'])

    print(model.summary())
    # Save model
    model.save(model_path)
    print(f"{time.asctime()} 模型生成完成")


def predict_model():
    emb_dict = get_dict()
    # 包括了EOS SOS的长度
    vocabulary_size = len(emb_dict) + 3
    embedding_dim = int(pow(vocabulary_size, 1.0 / 4))
    latent_dim = embedding_dim * 40

    model = load_model(model_path)

    # encoder
    encoder_inputs = model.input[0]
    # encoder_outputs, state_fh_enc, state_fc_enc, state_bh_enc, state_bc_enc = model.layers[3].output
    state_h_enc = model.layers[8].output
    state_c_enc = model.layers[9].output
    encoder_output, _, _, _, _ = model.layers[2].output

    encoder_model = Model(encoder_inputs, [encoder_output, state_h_enc, state_c_enc])

    # decoder
    decoder_inputs = model.input[1]
    embedding = model.layers[7]
    dec_embedding_inputs = embedding(decoder_inputs)
    encoder_output_decoder_in = Input(shape=(None, latent_dim * 2))
    decoder_state_input_h = Input(shape=(latent_dim * 2,), name='de_input_h')
    decoder_state_input_c = Input(shape=(latent_dim * 2,), name='de_input_c')
    decoder_states_inputs = [decoder_state_input_h, decoder_state_input_c]
    decoder_lstm = model.layers[11]
    decoder_outputs, state_h_dec, state_c_dec = decoder_lstm(
        dec_embedding_inputs, initial_state=decoder_states_inputs)
    decoder_states = [state_h_dec, state_c_dec]

    # attention
    # attention层
    # attention = Dense(1, activation='tanh')(encoder_outputs)
    # attention = Flatten()(attention)
    # attention = Activation('softmax')(attention)
    # attention = RepeatVector(latent_dim * 2)(attention)
    # attention = Permute([2, 1])(attention)
    # sent_dense = Multiply()([decoder_outputs, attention])
    dense = model.layers[3]
    attention = dense(encoder_output_decoder_in)
    attention = Flatten()(attention)
    attention = Activation('softmax')(attention)
    attention = RepeatVector(latent_dim * 2)(attention)
    attention = Permute([2, 1])(attention)
    sent_dense = Multiply()([decoder_outputs, attention])
    # flatten = model.layers[4]
    # attention = flatten(attention)
    # activation = model.layers[5]
    # attention = activation(attention)
    # repeat_vec = model.layers[11]
    # attention = repeat_vec(attention)
    # premute = model.layers[12]
    # attention = premute(attention)
    # multiply = model.layers[13]
    # to_dense = multiply(attention)

    decoder_dense = model.layers[14]
    decoder_outputs = decoder_dense(sent_dense)
    decoder_model = Model([encoder_output_decoder_in,
                           decoder_state_input_h,
                           decoder_state_input_c,
                           decoder_inputs],
                          [decoder_outputs] + decoder_states)
    return encoder_model, decoder_model


def predict(input_str):
    emb_dict = get_dict()

    # 这个size是包括了SOS EOS
    # 而且视为range()的右不包括，所以加了3
    vocabulary_size = len(emb_dict) + 3

    # 对输入进行分词
    cut = jieba.cut(input_str)
    token = []
    for i in cut:
        token.append(i)

    # 将分词后的列表按词典转换
    orig_dict = emb_dict
    input_seq = [[]]
    for word in token:
        try:
            index = orig_dict[word]
            input_seq[0].append(index)

        # 遇到词典不存在的词就跳过
        except KeyError:
            pass

    output_seq = []
    predict_seq = np.array(vocabulary_size - 2)

    encoder, decoder = predict_model()

    # 判断是否输入不在词典中
    try:
        encoder_out_decoder, h, c = encoder.predict(input_seq)
        while predict_seq != vocabulary_size - 1 and len(output_seq) < predict_maxlen:
            output_tokens, h, c = decoder.predict([encoder_out_decoder, h, c, np.array([[predict_seq]])])
            predict_seq = int(np.argmax(output_tokens[0, 0]))
            output_seq.append(predict_seq)

        # 翻转词典
        revers_dict = {}
        for key, val in orig_dict.items():
            revers_dict[val] = key

        # 将数字转换为字符
        output_str = ''
        for word in output_seq[:-1]:
            output_str += revers_dict[word]
        return output_str

    except IndexError:
        return '？'


# 数据预处理
# noinspection PyTypeChecker
def pre_precess():
    print(f"{time.asctime()} 读取训练数据...")
    data_loader = DataInitialize(data_path, ex_dict_path)
    # 加载数据
    data_loader.load_data()
    # 将数据向量化
    data_loader.word_to_vec()
    # 保存字典
    with open(dict_path, 'w', encoding='utf-8') as file:
        json.dump(data_loader.dict, file)

    encoder_input_data = np.array(pad_sequences(data_loader.input_vec, padding='post'))
    decoder_padding_data = np.array(pad_sequences(data_loader.output_vec, padding='post'))
    # 确定相同长度的sequence
    if len(encoder_input_data[0]) > len(decoder_padding_data[0] + 1):
        padding_len = len(encoder_input_data[0] + 1)
    else:
        padding_len = len(decoder_padding_data[0] + 1)
        encoder_input_data = np.array(pad_sequences(data_loader.input_vec, padding='post', maxlen=padding_len))

    decoder_origin = np.array(data_loader.output_vec)
    # 这里的padding - 1是因为在padding后要添加一个SOS
    decoder_input_data = padding_sign(pad_sequences(decoder_origin, padding='post', maxlen=padding_len - 1),
                                      len(data_loader.dict), mode=True)
    decoder_target_data = pad_sequences(padding_sign(decoder_origin, len(data_loader.dict), mode=False),
                                        padding='post',
                                        maxlen=padding_len)
    # 保存训练数据
    np.save(encoder_input, encoder_input_data)
    np.save(decoder_input, decoder_input_data)
    np.save(decoder_output, decoder_target_data)
    print(f"{time.asctime()} 训练数据处理完成")


application_path = Path(__file__).parent
base_dir = application_path
works_dir = base_dir / 'workspace'
train_dir = works_dir / 'train_data'
data_path = works_dir / 'train.xlsx'
train_config_path = works_dir / 'train_config.txt'
ex_dict_path = works_dir / 'ext_dict.txt'
dict_path = train_dir / 'words_dictionary.txt'
encoder_input = train_dir / 'encoder_input.npy'
decoder_input = train_dir / 'decoder_input.npy'
decoder_output = train_dir / 'decoder_output.npy'
model_path = train_dir / 's2s.h5'

with open(train_config_path, 'r', encoding='UTF-8') as f:
    train_config = json.load(f)

predict_maxlen = train_config['predict_maxlen']
