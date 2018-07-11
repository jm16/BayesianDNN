
import numpy as np
import pandas as pd
from math import sqrt
from numpy import concatenate
from pandas import concat
from sklearn.metrics import mean_squared_error
from sklearn.externals import joblib
from keras.models import Sequential
from keras.layers import Dense
from keras.layers import LSTM
from keras.layers.core import Dropout
from keras.callbacks import EarlyStopping
from sklearn.pipeline import make_pipeline
from keras.regularizers import L1L2
import matplotlib.pyplot as plt
from keras import optimizers
from keras.layers import LeakyReLU
from keras.layers import BatchNormalization
from keras import layers 
from keras import backend as K
from keras.callbacks import TensorBoard
import os 
# from keras import regularizers
# np.random.seed(777)


def multivariate_ts_to_supervised_extra_lag(data, n_in=1, n_out=1, return_threshold=0, columns=[0,1,2,3]):
    """
    Convert series to supervised learning problem. The holding period is assumed to be open to open.
    Alteratively, you may want to hold from open to close. 
    """
    
    df = pd.DataFrame(data)
    # print(df)
    df.columns = range(df.shape[1])
    #get open to high/low return, then drop (non differenced) ohlc from df
    return_min = df.iloc[:,2].shift(-n_out)/df.iloc[:,0].shift(-1)   -1 
    return_max = df.iloc[:,1].shift(-n_out)/df.iloc[:,0].shift(-1)   -1 
    df.drop(range(len(columns)),1, inplace=True)
    # print(df.columns)
    df.columns = range(1, len(df.columns)+1)
    n_vars = df.shape[1]
    cols, names = list(), list()
    # exlude most recent data which, for trading, is not yet available
    for i in range(n_in, 1, -1):
       cols.append(df.shift(i))
       names += [('var%d(t-%d)' % (j+1, i)) for j in range(n_vars)]
    
    cols.append(df)
    names += [('var%d' % (j+1)) for j in range(n_vars)]
    # forecast sequence (t+n_out)
    cols.append(df.iloc[:,0].shift(-(2)))
    cols.append(df.iloc[:,0].shift(-(n_out+1)))
    names.append('periodic_return')
    names.append('return')
    agg = concat(cols, axis=1)
    agg.columns = names
    
    agg['return'] = agg['return']+1
    agg['return'] = agg['return'].rolling(n_out).apply(np.prod,raw=False)-1
    
    agg['return_min'] = return_min
    agg['return_max'] = return_max

    agg['down'] = 0
    agg.loc[(agg['return_min'] < - return_threshold),'down'] = 1 

    agg['flat'] = 0
    agg.loc[((agg['return_max'] <= return_threshold) & (agg['return_min'] >= - return_threshold)),'flat'] = 1

    agg['up'] = 0
    agg.loc[(agg['return_max'] > return_threshold),'up'] = 1 

    agg.drop('return', 1, inplace=True)

#    agg=agg[agg.index%(n_out)==0]
#    if dropna:
#        agg.dropna(inplace=True)
        
    agg = agg[n_in:] # drop na at the head
    agg = agg.fillna(0)  #fill the next periods prediction with 0 so no error in scaling is raised
    return agg    


def get_returns(data, columns=[1,2,3,4], dropna=True):
    """
    Create new DataFrame with ohlc (needed for open-to-high and open-to-low returns)
     and ohlc.pct_change() and other columns left unchanged.
    """

    cols =  list(data.columns)
    pct_change_cols = []
    data_returns= data.copy(deep=True)
    ohlc = data_returns.iloc[:,0:4]
    ohlc.columns = ['o','h', 'l', 'c']

    for i in columns:
        data_returns[i]=data_returns[i].pct_change()
    

    data_returns = ohlc.join(data_returns)


    if dropna:
        data_returns.dropna(inplace=True)
        data_returns.replace([np.inf, -np.inf], 0,inplace=True)
    
       
    return data_returns  




def fit_model(model, train_X, train_y, val_X, val_y, batch, n_epochs, n_neurons, n_layers, lags, n_features, breg, kreg, rreg, lr, lrd, do):
    
    n_obs = n_features*(lags)

    tb = TensorBoard(log_dir='./Graph', histogram_freq=0,  
          write_graph=True, write_images=True)

    neuron_decay_factor_per_layer = 1 #0.75

    # design network
    if model == None:
        model = Sequential()
        model.add(BatchNormalization( input_shape=(n_obs,)))
       



        for i in range(n_layers):   
            model.add(Dense(n_neurons,bias_regularizer=breg, kernel_regularizer=kreg))
            model.add(BatchNormalization()) 
            model.add(layers.Activation('relu'))
            model.add(Dropout(do))   
            n_neurons = int(n_neurons*neuron_decay_factor_per_layer)
        
        
        model.add(Dense(3))
        model.add(BatchNormalization()) 
        model.add(layers.Activation('softmax'))
        
    # adam = optimizers.Adam(lr=lr, beta_1=0.9, beta_2=0.999, epsilon=1e-08, decay=lrd)
    nadam = optimizers.Nadam(lr=lr, beta_1=0.9, beta_2=0.999, epsilon=1e-08, schedule_decay=0.004)
    model.compile(loss='categorical_crossentropy', optimizer=nadam, metrics=['accuracy'])#mean_squared_error

    history = model.fit(train_X, train_y, epochs=n_epochs,
                  validation_data=(val_X, val_y),
                  batch_size=batch, 
                  verbose=2, shuffle=False, 
                 callbacks= [tb]#[EarlyStopping(monitor='val_loss', patience=100, verbose=2, mode='auto')]
                    )
    return model, history    


def train(model, dataset, train_pct, lags, n_epochs, batch, n_neurons, layers, n_features, breg, kreg, rreg, lr, lrd, do, p_out,rt):
    
    n_obs = (n_features)*(lags)

    dataset_returns = pd.DataFrame(dataset)
    
    dataset_returns = get_returns(dataset_returns)#, columns=[1,2,3,4,5,6])
    
    values = dataset_returns.values.astype('float32')
    values_encoded = values#encode(values)
    
    reframed = multivariate_ts_to_supervised_extra_lag(values_encoded, lags, p_out,rt)#, columns=[1,2,3,4,5,6])
    print(reframed.head(10))

    print("down/flat/up:")
    print(reframed.down.sum())
    print(reframed.flat.sum())
    print(reframed.up.sum())
    


    reframed_values=reframed.values
    train, test = reframed_values[:int(train_pct*len(reframed)), :] , reframed_values[int(train_pct*len(reframed)):, :]
    # split into input and outputs
    train_X, train_y = train[:, :n_obs], train[:, -3:]
    test_X, test_y = test[:, :n_obs], test[:, -3:]
    periodic_return = test[:,-6]
    low_return = test[:,-5]
    high_return = test[:,-4]

    #standardize
    train_X_mean = np.mean(train_X, 0)
    train_X_std = np.std(train_X, 0)

    train_X = (train_X - np.full(train_X.shape, train_X_mean)) / \
            np.full(train_X.shape, train_X_std)


    # train_y_mean = np.mean(train_y)
    # train_y_std = np.std(train_y)

    #save mean and std to disk. This is needed at test time 
    scalers = pd.DataFrame()
    scalers["train_X_mean"] = train_X_mean
    scalers["train_X_std"] = train_X_std
    # scalers["train_y_mean"] = train_y_mean
    # scalers["train_y_std"] = train_y_std
    scalers.to_csv('scalers.csv', header = True, index=True, encoding='utf-8')


    train_y_normalized = train_y#(train_y - train_y_mean) / train_y_std
    # train_y_normalized = np.array(train_y_normalized, ndmin = 2).T

    test_X = (test_X - np.full(test_X.shape, train_X_mean)) / \
            np.full(test_X.shape, train_X_std)

    test_y_normalized = test_y#(test_y - train_y_mean) / train_y_std
    # test_y_normalized = np.array(test_y_normalized, ndmin = 2).T
    
    # fit the model
    fitted_model, history = fit_model(model, train_X, train_y_normalized, test_X, test_y_normalized, batch, n_epochs, n_neurons, layers, lags, n_features, breg, kreg, rreg, lr, lrd, do)

    return test_X, test_y, periodic_return, low_return, high_return, fitted_model,#, train_y_mean, train_y_std#meanerror_scores,train_loss.mean(axis=1), test_loss.mean(axis=1), lstm_model, lags, batch, scaling_method

def out_of_sample_test(test_X, test_y, periodic_return, low_return, high_return,  model):#train_y_mean, train_y_std,

    
    mc_dropout = True

    if mc_dropout == True:
        ### MC Dropout
        T = 1000
        # We want to use Dropout at test time, not just at training time as usual. To do this we tell Keras to predict with learning_phase set to true.  
        predict_stochastic = K.function([model.layers[0].input, K.learning_phase()], [model.layers[-1].output])

        Y_hat = np.array([predict_stochastic([test_X, 1]) for _ in range(T)])

        # if y was standardized
        # Y_hat = Y_hat * train_y_std + train_y_mean
        yhat_std = np.std(Y_hat, 0)
        yhat = np.mean(Y_hat, 0)
        yhat = yhat.squeeze()
        yhat_std = yhat_std.squeeze()
    else:
        #ordinary prediction
        yhat = model.predict(test_X, batch_size=512)
        yhat_std = np.zeros(yhat.shape)



    output_df=pd.DataFrame()
    output_df['down_prediction'] = pd.Series(yhat[:,0])
    output_df['flat_prediction'] = pd.Series(yhat[:,1])
    output_df['up_prediction'] = pd.Series(yhat[:,2])

    output_df['down_prediction_std'] = pd.Series(yhat_std[:,0])
    output_df['flat_prediction_std'] = pd.Series(yhat_std[:,1])
    output_df['up_prediction_std'] = pd.Series(yhat_std[:,2])
    # output_df['return']=pd.Series(y_inverted)#reframed['return']
    output_df['down_actual'] = pd.Series(test_y[:,0])
    output_df['flat_actual'] = pd.Series(test_y[:,1])
    output_df['up_actual'] = pd.Series(test_y[:,2])
    output_df['periodic_return'] = pd.Series(periodic_return)
    output_df['low_return'] = pd.Series(low_return)
    output_df['high_return'] = pd.Series(high_return)


    # return dataset_returns with OOS predictions
    return output_df
def equity_curve(dataset, m, periods_in_year, plot, softmax_threshold, profit_taking_threshold, bayesian_threshold):

    dataset.dropna(inplace=True)
    transaction_cost = 2/100000
    
    print("predicted percentages:")
    print(dataset[['down_prediction','flat_prediction','up_prediction']].head())
    print(dataset[['down_prediction','flat_prediction','up_prediction']].tail())

    
    # loop over Bayesian confidence
    for p in bayesian_threshold:
        print('>FOR MODEL: %s' %m)
        print("return > %s  x std: "%p)

        # loop over softmax threshold. The softmax output can provide information about the strength of the trading signal. However, it can be very high even if the cofidence of the network is low
        # this is the reason we need a Bayesian uncertainty.
        for i in softmax_threshold:
            # if prediction confidence is less than p*std ignore prediction as it is deemed not stat significant
            dataset.loc[(dataset['down_prediction'] < p*dataset['down_prediction_std']), 'down_prediction'] = 0 
            dataset.loc[(dataset['up_prediction'] < p*dataset['up_prediction_std']),'up_prediction'] = 0 

            #get signal according to softmax output
            dataset['signal_%.2f_sigma' %i] = 0#
            dataset.loc[(dataset['down_prediction'] > i) & (dataset['up_prediction'] <  dataset['down_prediction']), 'signal_%.2f_sigma' %i] = -1
            dataset.loc[(dataset['up_prediction'] > i) & (dataset['up_prediction'] >  dataset['down_prediction']),'signal_%.2f_sigma' %i] = 1


            dataset['signal_%.2f_sigma' %i]=dataset['signal_%.2f_sigma' %i].fillna(0)

            #trading result with profit taking threshold, if no profit taking is triggered, trade result = periodic return
            dataset['trade_result_%.2f_sigma' %i]=dataset['periodic_return']*dataset['signal_%.2f_sigma' %i]
            dataset.loc[(dataset['signal_%.2f_sigma' %i]==1) & (dataset['high_return'] > profit_taking_threshold), 'trade_result_%.2f_sigma' %i] = profit_taking_threshold
            dataset.loc[(dataset['signal_%.2f_sigma' %i]==-1) & ((dataset['low_return'] < - profit_taking_threshold)) , 'trade_result_%.2f_sigma' %i] = profit_taking_threshold

            dataset['trade_%.2f_sigma' %i]= (dataset['signal_%.2f_sigma' %i].shift(1)!=dataset['signal_%.2f_sigma' %i]).astype(int)
            dataset['equity_curve_%.2f_sigma' %i]=(dataset['trade_result_%.2f_sigma' %i]+1).cumprod()

            dataset['noncomp_curve_%.2f_sigma' %i]=(dataset['trade_result_%.2f_sigma' %i]).cumsum()   

            # compute the percentage of correct predictions 
            dataset['correct_prediction_%.2f_sigma' %i]= None 
            dataset.loc[dataset['trade_result_%.2f_sigma' %i]>0, 'correct_prediction_%.2f_sigma' %i] = 1
            dataset.loc[dataset['trade_result_%.2f_sigma' %i]<0, 'correct_prediction_%.2f_sigma' %i] = 0

            # compute transaction costs taking into account that if profit taking is triggered, two trades happend even if next period position is on the same side. 
            dataset['trade_result_%.2f_sigma_after_tc' %i] = dataset['trade_result_%.2f_sigma' %i]
            dataset.loc[(dataset['signal_%.2f_sigma' %i] + dataset['signal_%.2f_sigma' %i].shift(1)).abs()==1 , 'trade_result_%.2f_sigma_after_tc' %i] = (dataset['trade_result_%.2f_sigma' %i]+1) * (1.0-transaction_cost*dataset['trade_%.2f_sigma' %i]) -1
            dataset.loc[(dataset['signal_%.2f_sigma' %i] + dataset['signal_%.2f_sigma' %i].shift(1))==0,'trade_result_%.2f_sigma_after_tc' %i] = (dataset['trade_result_%.2f_sigma' %i]+1) * (1.0-2*transaction_cost*dataset['trade_%.2f_sigma' %i]) -1
            dataset.loc[((dataset['signal_%.2f_sigma' %i] + dataset['signal_%.2f_sigma' %i].shift(1))==2) & (dataset['high_return'].shift(1) > profit_taking_threshold) , 'trade_result_%.2f_sigma_after_tc' %i] = (dataset['trade_result_%.2f_sigma' %i]+1) * (1.0-2*transaction_cost*dataset['trade_%.2f_sigma' %i]) -1
            dataset.loc[((dataset['signal_%.2f_sigma' %i] + dataset['signal_%.2f_sigma' %i].shift(1))==-2) & (dataset['low_return'] < - profit_taking_threshold) , 'trade_result_%.2f_sigma_after_tc' %i] = (dataset['trade_result_%.2f_sigma' %i]+1) * (1.0-2*transaction_cost*dataset['trade_%.2f_sigma' %i]) -1
            # dataset['trade_result_%.2f_sigma_after_tc' %i] = (dataset['trade_result_%.2f_sigma' %i]+1) * (1.0-transaction_cost*dataset['trade_%.2f_sigma' %i]) -1
            dataset['equity_curve_%.2f_sigma_after_tc' %i]=(dataset['trade_result_%.2f_sigma_after_tc' %i]+1).cumprod()

            

            #If there are any trades at all, calculate some statistics.
            if (len(dataset['correct_prediction_%.2f_sigma' %i].dropna()))>0:

                pct_correct = sum(dataset['correct_prediction_%.2f_sigma' %i].dropna())/len(dataset['correct_prediction_%.2f_sigma' %i].dropna())
                print('Percent correct %.2f_sigma: ' %i + str((pct_correct)*100)+" %")


                # Does the model have a long or short bias?
                percent_betting_up = dataset['signal_%.2f_sigma' %i][dataset['signal_%.2f_sigma' %i]>0].sum()/len(dataset['signal_%.2f_sigma' %i])#[dataset['signal_%.2f_sigma' %i]!=0])
                percent_betting_down = -dataset['signal_%.2f_sigma' %i][dataset['signal_%.2f_sigma' %i]<0].sum()/len(dataset['signal_%.2f_sigma' %i])#[dataset['signal_%.2f_sigma' %i]!=0])
                out_of_market = 1.00 - (percent_betting_up + percent_betting_down)
                print('percentage of periods betting up %.2f_sigma : ' %(i)+str(percent_betting_up*100)+' %'
                      +'; percentage of periods betting down: %.2f_sigma  ' %i+str(percent_betting_down*100)+' %'
                      +'; percentage of periods staying out of the market: %.2f_sigma  ' %i+str(out_of_market*100)+' %')
                
                #How many trades were there
                total_trades = dataset['trade_%.2f_sigma' %i].sum()
                print('There were %s total trades for %.2f_sigma.' %(total_trades, i))
                print('The annualised_sharpe for %.2f_sigma. is: %.2f.' %(i, annualised_sharpe(dataset['trade_result_%.2f_sigma' %i], periods_in_year)))
                print('The CAGR for %.2f_sigma. is: %.2f percent.' %(i, annual_return(dataset['equity_curve_%.2f_sigma' %i],periods_in_year)*100))

                print('The annualised_sharpe for %.2f_sigma. after commissions is: %.2f.' %(i, annualised_sharpe(dataset['trade_result_%.2f_sigma_after_tc' %i], periods_in_year)))
                print('The CAGR for %.2f_sigma. is: %.2f percent. after commissions' %(i, annual_return(dataset['equity_curve_%.2f_sigma_after_tc' %i],periods_in_year)*100))

                average_gain = (dataset['trade_result_%.2f_sigma' %i][dataset['trade_result_%.2f_sigma' %i]>0]).mean()
                average_loss = (dataset['trade_result_%.2f_sigma' %i][dataset['trade_result_%.2f_sigma' %i]<0]).mean()
                print('average_gain: ' +str(average_gain))
                print('average_loss: ' +str(average_loss))
                print('average_trade: ' +str((dataset['trade_result_%.2f_sigma' %i][dataset['trade_result_%.2f_sigma' %i]!=0]).mean()))
                print("\n")

                if plot:
                    if not os.path.exists('./Equity_curves'):
                        os.makedirs('Equity_curves')
                    dataset['equity_curve_%.2f_sigma' %i].plot()
                    plt.title('Equity Curve %.2f softmax %.2f Bayesian_z_score' %(i,p))
                    plt.ylabel('Value')
                    plt.xlabel('Period')
                    plt.savefig('Equity_curves/equity_curve_%.2f_softmax_%.2f_Bayesian_z_score.png' %(i,p))
                    plt.close() 
    if plot:
        ((dataset['periodic_return']+1).cumprod()).plot()
        plt.title('Asset price series')
        plt.ylabel('price')
        plt.xlabel('period')
        plt.savefig('Equity_curves/Asset_price_series.png')
        plt.close() 
    return dataset

def annualised_sharpe(returns, periods_in_year):
    '''
    Assumes daily returns are supplied. If not change periods in year.
    '''
    
    # periods_in_year = 368751#252
    return np.sqrt(periods_in_year) * returns.mean() / returns.std()

def annual_return(equity_curve, periods_in_year):
    # periods_in_year = 368751#252
    return equity_curve.values[-1]**(periods_in_year/len(equity_curve))-1
    

        