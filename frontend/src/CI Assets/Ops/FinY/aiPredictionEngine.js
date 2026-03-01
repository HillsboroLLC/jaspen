// AI Prediction Engine for FinY Benefit Model
// Integrates TensorFlow.js for sophisticated financial forecasting

import * as tf from '@tensorflow/tfjs';

export class FinYPredictionEngine {
  constructor() {
    this.models = new Map();
    this.isInitialized = false;
    this.modelCache = new Map();
  }

  async initialize() {
    if (this.isInitialized) return;
    
    try {
      // Initialize TensorFlow.js
      await tf.ready();
      console.log('TensorFlow.js initialized successfully');
      this.isInitialized = true;
    } catch (error) {
      console.error('Failed to initialize TensorFlow.js:', error);
      throw error;
    }
  }

  // Linear Regression Model for basic trend analysis
  async createLinearRegressionModel(inputShape = 1) {
    const model = tf.sequential({
      layers: [
        tf.layers.dense({ inputShape: [inputShape], units: 1, activation: 'linear' })
      ]
    });

    model.compile({
      optimizer: tf.train.adam(0.01),
      loss: 'meanSquaredError',
      metrics: ['mae']
    });

    return model;
  }

  // Neural Network Model for complex pattern recognition
  async createNeuralNetworkModel(inputShape = 12) {
    const model = tf.sequential({
      layers: [
        tf.layers.dense({ inputShape: [inputShape], units: 64, activation: 'relu' }),
        tf.layers.dropout({ rate: 0.2 }),
        tf.layers.dense({ units: 32, activation: 'relu' }),
        tf.layers.dropout({ rate: 0.1 }),
        tf.layers.dense({ units: 16, activation: 'relu' }),
        tf.layers.dense({ units: 1, activation: 'linear' })
      ]
    });

    model.compile({
      optimizer: tf.train.adam(0.001),
      loss: 'meanSquaredError',
      metrics: ['mae', 'mse']
    });

    return model;
  }

  // Time Series LSTM Model for sequential data
  async createTimeSeriesModel(sequenceLength = 6, features = 1) {
    const model = tf.sequential({
      layers: [
        tf.layers.lstm({
          units: 50,
          returnSequences: true,
          inputShape: [sequenceLength, features]
        }),
        tf.layers.dropout({ rate: 0.2 }),
        tf.layers.lstm({
          units: 50,
          returnSequences: false
        }),
        tf.layers.dropout({ rate: 0.2 }),
        tf.layers.dense({ units: 25, activation: 'relu' }),
        tf.layers.dense({ units: 1, activation: 'linear' })
      ]
    });

    model.compile({
      optimizer: tf.train.adam(0.001),
      loss: 'meanSquaredError',
      metrics: ['mae']
    });

    return model;
  }

  // Prepare data for training
  prepareTrainingData(baseline, actual, periods) {
    const features = [];
    const labels = [];

    // Create feature vectors from baseline and actual data
    for (let i = 0; i < periods.length; i++) {
      if (actual[i] > 0) { // Only use periods with actual data
        const feature = [
          baseline[i],
          i + 1, // Period index (time component)
          this.calculateTrend(baseline, i),
          this.calculateSeasonality(i, periods.length),
          this.calculateVolatility(baseline, i)
        ];
        features.push(feature);
        labels.push(actual[i]);
      }
    }

    return {
      features: tf.tensor2d(features),
      labels: tf.tensor1d(labels)
    };
  }

  // Calculate trend component
  calculateTrend(data, index) {
    if (index === 0) return 0;
    const windowSize = Math.min(3, index);
    let sum = 0;
    for (let i = 1; i <= windowSize; i++) {
      sum += data[index - i + 1] - data[index - i];
    }
    return sum / windowSize;
  }

  // Calculate seasonality component
  calculateSeasonality(index, totalPeriods) {
    // Simple sinusoidal seasonality
    return Math.sin((2 * Math.PI * index) / totalPeriods);
  }

  // Calculate volatility component
  calculateVolatility(data, index) {
    if (index < 2) return 0;
    const windowSize = Math.min(3, index);
    const values = data.slice(Math.max(0, index - windowSize), index + 1);
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const variance = values.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / values.length;
    return Math.sqrt(variance);
  }

  // Generate predictions using selected model
  async generatePredictions(metricData, modelType = 'neural_network', options = {}) {
    await this.initialize();

    const { baseline, actual, financialImpact, costPerUnit } = metricData;
    const { confidence = 85, seasonality = true, trendAnalysis = true } = options;

    try {
      let predictions = [];

      switch (modelType) {
        case 'linear_regression':
          predictions = await this.linearRegressionPredict(baseline, actual);
          break;
        case 'neural_network':
          predictions = await this.neuralNetworkPredict(baseline, actual);
          break;
        case 'time_series':
          predictions = await this.timeSeriesPredict(baseline, actual);
          break;
        case 'polynomial':
          predictions = await this.polynomialPredict(baseline, actual);
          break;
        default:
          predictions = await this.hybridPredict(baseline, actual, options);
      }

      // Apply business logic adjustments
      predictions = this.applyBusinessLogic(predictions, baseline, financialImpact);

      // Add confidence intervals
      predictions = this.addConfidenceIntervals(predictions, confidence);

      // Apply seasonality if enabled
      if (seasonality) {
        predictions = this.applySeasonality(predictions, baseline.length);
      }

      return predictions;

    } catch (error) {
      console.error('Prediction generation failed:', error);
      // Fallback to simple statistical prediction
      return this.fallbackPredict(baseline, actual);
    }
  }

  // Linear regression prediction
  async linearRegressionPredict(baseline, actual) {
    const model = await this.createLinearRegressionModel();
    
    // Prepare training data
    const trainX = [];
    const trainY = [];
    
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        trainX.push([i]);
        trainY.push(actual[i]);
      }
    }

    if (trainX.length < 2) {
      return this.fallbackPredict(baseline, actual);
    }

    const xs = tf.tensor2d(trainX);
    const ys = tf.tensor1d(trainY);

    // Train the model
    await model.fit(xs, ys, {
      epochs: 100,
      verbose: 0,
      validationSplit: 0.2
    });

    // Generate predictions
    const predictions = [];
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        predictions.push(actual[i]);
      } else {
        const pred = model.predict(tf.tensor2d([[i]]));
        const value = await pred.data();
        predictions.push(Math.max(0, value[0]));
        pred.dispose();
      }
    }

    // Cleanup
    xs.dispose();
    ys.dispose();
    model.dispose();

    return predictions;
  }

  // Neural network prediction
  async neuralNetworkPredict(baseline, actual) {
    const model = await this.createNeuralNetworkModel(5);
    
    const features = [];
    const labels = [];

    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        const feature = [
          baseline[i],
          i + 1,
          this.calculateTrend(baseline, i),
          this.calculateSeasonality(i, baseline.length),
          this.calculateVolatility(baseline, i)
        ];
        features.push(feature);
        labels.push(actual[i]);
      }
    }

    if (features.length < 3) {
      return this.fallbackPredict(baseline, actual);
    }

    const xs = tf.tensor2d(features);
    const ys = tf.tensor1d(labels);

    // Train the model
    await model.fit(xs, ys, {
      epochs: 200,
      batchSize: Math.min(32, features.length),
      verbose: 0,
      validationSplit: 0.2,
      callbacks: {
        onEpochEnd: (epoch, logs) => {
          if (epoch % 50 === 0) {
            console.log(`Epoch ${epoch}: loss = ${logs.loss.toFixed(4)}`);
          }
        }
      }
    });

    // Generate predictions
    const predictions = [];
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        predictions.push(actual[i]);
      } else {
        const feature = tf.tensor2d([[
          baseline[i],
          i + 1,
          this.calculateTrend(baseline, i),
          this.calculateSeasonality(i, baseline.length),
          this.calculateVolatility(baseline, i)
        ]]);
        
        const pred = model.predict(feature);
        const value = await pred.data();
        predictions.push(Math.max(0, value[0]));
        
        feature.dispose();
        pred.dispose();
      }
    }

    // Cleanup
    xs.dispose();
    ys.dispose();
    model.dispose();

    return predictions;
  }

  // Time series LSTM prediction
  async timeSeriesPredict(baseline, actual) {
    const sequenceLength = 6;
    const model = await this.createTimeSeriesModel(sequenceLength);

    // Prepare sequences
    const sequences = [];
    const targets = [];

    for (let i = sequenceLength; i < baseline.length; i++) {
      if (actual[i] > 0) {
        const sequence = [];
        for (let j = i - sequenceLength; j < i; j++) {
          sequence.push([baseline[j]]);
        }
        sequences.push(sequence);
        targets.push(actual[i]);
      }
    }

    if (sequences.length < 2) {
      return this.fallbackPredict(baseline, actual);
    }

    const xs = tf.tensor3d(sequences);
    const ys = tf.tensor1d(targets);

    // Train the model
    await model.fit(xs, ys, {
      epochs: 100,
      batchSize: Math.min(16, sequences.length),
      verbose: 0,
      validationSplit: 0.2
    });

    // Generate predictions
    const predictions = [];
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        predictions.push(actual[i]);
      } else if (i >= sequenceLength) {
        const sequence = [];
        for (let j = i - sequenceLength; j < i; j++) {
          sequence.push([baseline[j]]);
        }
        
        const input = tf.tensor3d([sequence]);
        const pred = model.predict(input);
        const value = await pred.data();
        predictions.push(Math.max(0, value[0]));
        
        input.dispose();
        pred.dispose();
      } else {
        predictions.push(baseline[i]);
      }
    }

    // Cleanup
    xs.dispose();
    ys.dispose();
    model.dispose();

    return predictions;
  }

  // Polynomial regression prediction
  async polynomialPredict(baseline, actual, degree = 2) {
    const trainX = [];
    const trainY = [];
    
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        trainX.push(i);
        trainY.push(actual[i]);
      }
    }

    if (trainX.length < degree + 1) {
      return this.fallbackPredict(baseline, actual);
    }

    // Create polynomial features
    const polyFeatures = trainX.map(x => {
      const features = [];
      for (let d = 0; d <= degree; d++) {
        features.push(Math.pow(x, d));
      }
      return features;
    });

    const model = tf.sequential({
      layers: [
        tf.layers.dense({ inputShape: [degree + 1], units: 1, activation: 'linear' })
      ]
    });

    model.compile({
      optimizer: tf.train.adam(0.01),
      loss: 'meanSquaredError'
    });

    const xs = tf.tensor2d(polyFeatures);
    const ys = tf.tensor1d(trainY);

    await model.fit(xs, ys, {
      epochs: 200,
      verbose: 0
    });

    // Generate predictions
    const predictions = [];
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        predictions.push(actual[i]);
      } else {
        const polyFeature = [];
        for (let d = 0; d <= degree; d++) {
          polyFeature.push(Math.pow(i, d));
        }
        
        const input = tf.tensor2d([polyFeature]);
        const pred = model.predict(input);
        const value = await pred.data();
        predictions.push(Math.max(0, value[0]));
        
        input.dispose();
        pred.dispose();
      }
    }

    // Cleanup
    xs.dispose();
    ys.dispose();
    model.dispose();

    return predictions;
  }

  // Hybrid prediction combining multiple models
  async hybridPredict(baseline, actual, options) {
    const models = ['linear_regression', 'neural_network'];
    const predictions = [];

    for (const modelType of models) {
      try {
        const pred = await this.generatePredictions(
          { baseline, actual }, 
          modelType, 
          { ...options, confidence: 85 }
        );
        predictions.push(pred);
      } catch (error) {
        console.warn(`Model ${modelType} failed, skipping:`, error);
      }
    }

    if (predictions.length === 0) {
      return this.fallbackPredict(baseline, actual);
    }

    // Ensemble averaging
    const ensemblePredictions = [];
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        ensemblePredictions.push(actual[i]);
      } else {
        const avgPrediction = predictions.reduce((sum, pred) => sum + pred[i], 0) / predictions.length;
        ensemblePredictions.push(avgPrediction);
      }
    }

    return ensemblePredictions;
  }

  // Apply business logic to predictions
  applyBusinessLogic(predictions, baseline, financialImpact) {
    return predictions.map((pred, index) => {
      const base = baseline[index];
      
      // Apply improvement constraints based on financial impact type
      switch (financialImpact) {
        case 'Cost Reduction':
          // For cost reduction, predictions should generally decrease
          return Math.min(pred, base * 0.7); // Max 30% reduction
        case 'Revenue Increase':
          // For revenue increase, predictions should generally increase
          return Math.max(pred, base * 1.05); // Min 5% increase
        case 'Cost Avoidance':
          // For cost avoidance, maintain or improve slightly
          return Math.max(pred, base * 0.95); // Max 5% decrease
        default:
          return pred;
      }
    });
  }

  // Add confidence intervals to predictions
  addConfidenceIntervals(predictions, confidence) {
    const confidenceLevel = confidence / 100;
    const margin = (1 - confidenceLevel) / 2;

    return predictions.map(pred => ({
      value: pred,
      lower: pred * (1 - margin),
      upper: pred * (1 + margin),
      confidence: confidence
    }));
  }

  // Apply seasonality patterns
  applySeasonality(predictions, periodCount) {
    return predictions.map((pred, index) => {
      const seasonalFactor = 1 + Math.sin((2 * Math.PI * index) / periodCount) * 0.1;
      return typeof pred === 'object' 
        ? { ...pred, value: pred.value * seasonalFactor }
        : pred * seasonalFactor;
    });
  }

  // Fallback prediction using simple statistical methods
  fallbackPredict(baseline, actual) {
    const predictions = [];
    
    for (let i = 0; i < baseline.length; i++) {
      if (actual[i] > 0) {
        predictions.push(actual[i]);
      } else {
        // Simple linear interpolation with improvement trend
        const improvementRate = 0.02; // 2% improvement per period
        const seasonalFactor = 1 + Math.sin((2 * Math.PI * i) / baseline.length) * 0.05;
        const prediction = baseline[i] * (1 + improvementRate * (i + 1)) * seasonalFactor;
        predictions.push(Math.max(0, prediction));
      }
    }
    
    return predictions;
  }

  // Model performance evaluation
  async evaluateModel(predictions, actual) {
    const actualValues = actual.filter(val => val > 0);
    const predValues = predictions.filter((_, index) => actual[index] > 0);

    if (actualValues.length === 0) return null;

    const mse = actualValues.reduce((sum, actual, i) => {
      return sum + Math.pow(actual - predValues[i], 2);
    }, 0) / actualValues.length;

    const mae = actualValues.reduce((sum, actual, i) => {
      return sum + Math.abs(actual - predValues[i]);
    }, 0) / actualValues.length;

    const rmse = Math.sqrt(mse);

    return { mse, mae, rmse };
  }

  // Cleanup resources
  dispose() {
    this.models.forEach(model => model.dispose());
    this.models.clear();
    this.modelCache.clear();
  }
}

// Export singleton instance
export const aiPredictionEngine = new FinYPredictionEngine();

