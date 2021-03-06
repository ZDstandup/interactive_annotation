# Basic import
import numpy as np
import matplotlib as mpl
mpl.use('TkAgg')
import matplotlib.pyplot as plt

# Compatible with Python2 and python3
import six

# load in an image as array
import skimage.io

# Keras, a high-level neural networks API
from keras import backend
from keras.models import Sequential
from keras.layers import convolutional as Convs
from keras.layers import normalization as Normal
from keras.layers import Activation,Lambda
from keras.layers.merge import add
from keras.regularizers import l2



def _bn_relu(input):
    # 标准化
    # 在Conv2D层后 使其特征轴平均值接近0 标准差接近1
    norm = Normal.BatchNormalization(axis=3)(input)
    # 设置激活函数 返回激活层
    return Activation("relu")(norm)



def _conv_bn_relu(**conv_params):
    # 卷积层->进行标准化->激励block
    # filters数目
    filters = conv_params["filters"]
    # filter形状
    kernel_size = conv_params["kernel_size"]
    # 数据窗口步长
    strides = conv_params.setdefault("strides", (1, 1))
    # 用0填充边界,使全图大小可以被步长整除
    padding = conv_params.setdefault("padding", "same")
    # 权值初始化
    kernel_initializer = conv_params.setdefault("kernel_initializer", "he_normal")
    # ref to
    # Delving Deep into Rectifiers: Surpassing Human-Level Performance on ImageNet Classification
    # 施加在权重上的正则项
    kernel_regularizer = conv_params.setdefault("kernel_regularizer", l2(1.e-4))

    def f(input):
        conv = Convs.Conv2D(filters=filters, kernel_size=kernel_size,
                            strides=strides, padding=padding,
                            kernel_initializer=kernel_initializer,
                            kernel_regularizer=kernel_regularizer)(input)
        return _bn_relu(conv)

    return f


def _bn_relu_conv(**conv_params):
    # 标准化->激励函数->卷积层
    # filters数目
    filters = conv_params["filters"]
    # filter的形状
    kernel_size = conv_params["kernel_size"]
    # 卷积步长
    strides = conv_params.setdefault("strides", (1, 1))
    # 用0填充边界,使全图大小可以被步长整除
    padding = conv_params.setdefault("padding", "same")
    # 权值初始化(filter)
    kernel_initializer = conv_params.setdefault("kernel_initializer", "he_normal")
    # 施加在权重上的正则项
    kernel_regularizer = conv_params.setdefault("kernel_regularizer", l2(1.e-4))

    def f(input):
        activation = _bn_relu(input)
        return Convs.Conv2D(filters=filters, kernel_size=kernel_size,
                      strides=strides, padding=padding,
                      kernel_initializer=kernel_initializer,
                      kernel_regularizer=kernel_regularizer)(activation)
    return f


def get_res(block_function, filters, repetitions, is_first_layer=False):
    def f(iter_tensor):
        for i in range(repetitions):
            if i == 0 and not is_first_layer:
                init_strides = (2, 2)
            else:
                init_strides = (1, 1)
            # repet 3、4、6、3 times
            iter_tensor = block_function(filters=filters, init_strides=init_strides,
                                   is_first_block_of_first_layer=(is_first_layer and i == 0))(iter_tensor)
        return iter_tensor

    return f


def bottleneck(filters, init_strides=(1, 1), is_first_block_of_first_layer=False):
    def f(input):
        if is_first_block_of_first_layer:
            # 第一层的第一个块需要初始化
            res = Convs.Conv2D(filters=filters, kernel_size=(1, 1),
                              strides=init_strides,
                              padding="same",
                              kernel_initializer="he_normal",
                              kernel_regularizer=l2(1e-4))(input)
        else:
            # conv_1_1是一个filter为1*1的卷积层
            res = _bn_relu_conv(filters=filters, kernel_size=(1, 1),
                                     strides=init_strides)(input)
        conv_3_3 = _bn_relu_conv(filters=filters, kernel_size=(3, 3))(res)

        res = _bn_relu_conv(filters=filters * 4, kernel_size=(1, 1))(conv_3_3)
        # res.filters*4 res.conv = 1*1
        input_shape = backend.int_shape(input)
        res_shape   = backend.int_shape(res)

        stride_width  = int(round(input_shape[1] / res_shape[1]))
        stride_height = int(round(input_shape[2] / res_shape[2]))

        shortcut = input

        # if same, Unnecessary
        if input_shape[3] != res_shape[3]:
            shortcut = Convs.Conv2D(filters=res_shape[3],
                                    kernel_size=(1, 1),
                                    strides=(stride_width, stride_height),
                                    padding="valid",
                                    kernel_initializer="he_normal",
                                    kernel_regularizer=l2(0.0001))(input)
        # add tensors
        return add([shortcut, res])

    return f





def build_model(input_shape = (3, 224, 224) , block_fn = bottleneck, repetitions = None):

    # 默认参数最好不要设为数组等可变量
    if repetitions == None:
        repetitions = [3, 4, 6, 3]

    # 解决python版本问题
    if isinstance(block_fn, six.string_types):
        block_fn = globals().get(block_fn)

    if backend.image_dim_ordering() == 'tf':
        input_shape = (input_shape[1], input_shape[2], input_shape[0])


    # 初始化顺序模型 得到实例对象model
    model = Sequential()

    # 将任意表达式封装为Layer对象，首个参数必为函数 故用lambda修饰为匿名函数
    lambda_layer = Lambda(lambda block: block, input_shape=input_shape)

    # 将lambda_layer封装进model中 作为第一层
    model.add(lambda_layer)

    filters = 64

    for i in range(len(repetitions)):
        block = get_res(block_fn, filters=filters,
                                repetitions=repetitions[i], is_first_layer=(i == 0))
        lambda_layer = Lambda(block)
        model.add(lambda_layer)
        filters *= 2

    return model

def main(input_path="input/traffic_3.png"):
    resnet50 = build_model()
    resnet50.summary()
    img = []
    img.append(skimage.io.imread(input_path))
    img_crop = np.array(img[0][0:224, 0:224, :3])
    img_feed = np.reshape(img_crop, [-1, 224, 224, 3])
    # 配置模型 loss损失函数 optimizer优化器
    resnet50.compile(loss='binary_crossentropy', optimizer='adadelta')
    # 进行计算并返回结果 28*28
    result = resnet50.predict(img_feed)
    print(result.shape)
    plt.figure()
    plt.imshow(np.squeeze(result[0, :, :, 0]))
    plt.show()



if __name__ == '__main__':
    main()