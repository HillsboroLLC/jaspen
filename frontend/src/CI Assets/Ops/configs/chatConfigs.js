// Enhanced chatConfigs.js - With Form Filling Capabilities

export const sipocConfig = {
  title: "SIPOC AI Guide",
  welcomeMessage: "Welcome to SIPOC! I'll help you map your process from Suppliers to Customers. I can also fill in example data to get you started. Just ask me to 'fill with example data' or ask questions about any section!",
  inputPlaceholder: "Ask me about suppliers, inputs, process steps, outputs, customers, or say 'fill example data'...",
  
  // YOUR ORIGINAL RESPONSES FROM THE FIRST SIPOC VERSION
  responses: {
    'suppliers': "Great question about suppliers! Think about who provides the inputs to your process. These can be internal departments, external vendors, or even automated systems. For each supplier, consider: What do they provide? What are your requirements from them? How do you communicate with them?",
    
    'inputs': "Inputs are everything that goes into your process - materials, information, resources, or triggers. Ask yourself: What does your process need to start? What information is required? What materials or resources are consumed? Don't forget about less obvious inputs like approvals or environmental conditions.",
    
    'process': "Your process steps should be high-level (5-7 steps typically). Focus on the main activities, not detailed sub-tasks. For each step, think about: What is the main activity? Who is responsible? How long does it typically take? What could go wrong here?",
    
    'outputs': "Outputs are what your process produces - products, services, information, or decisions. Consider: What does your process deliver? Who receives each output? What are the quality requirements? How do you measure success for each output?",
    
    'customers': "Customers are anyone who receives your outputs. They can be internal (other departments) or external (end customers). For each customer, think about: What do they expect? How do they use your output? What would make them satisfied? How do you get their feedback?",
    
    'scope': "Process scope defines the boundaries - where your process starts and ends. Be specific about: What triggers the process to begin? What signals the process is complete? What's included vs. excluded? This helps prevent scope creep and ensures everyone understands the boundaries."
  },
  
  defaultResponse: "I can help you with any aspect of your SIPOC. Try asking about suppliers, inputs, process steps, outputs, customers, or process scope. I can also fill in example data - just say 'fill example data'!",
  
  quickActions: [
    { label: "Help with Suppliers", message: "How do I identify suppliers?" },
    { label: "Process Steps", message: "How many process steps should I have?" },
    { label: "Define Scope", message: "How do I define process scope?" },
    { label: "Customer Requirements", message: "How do I identify customer requirements?" }
  ],
  
  // NEW: Form filling suggestions based on keywords
  formSuggestions: {
    'suppliers': (userMessage, currentData) => {
      // If user asks about suppliers and form is mostly empty, suggest some
      if (!currentData.processName) return null;
      
      const lowerMessage = userMessage.toLowerCase();
      if (lowerMessage.includes('example') || lowerMessage.includes('suggest')) {
        return {
          suppliers: [
            { id: 1, name: 'Internal Team', type: 'Internal', requirements: 'Qualified inputs', contact: 'team@company.com' },
            { id: 2, name: 'External Vendor', type: 'External', requirements: 'Quality materials', contact: 'vendor@supplier.com' }
          ]
        };
      }
      return null;
    },
    
    'process': (userMessage, currentData) => {
      const lowerMessage = userMessage.toLowerCase();
      if (lowerMessage.includes('example') || lowerMessage.includes('suggest')) {
        return {
          process: [
            { id: 1, step: 'Initiate', description: 'Start the process', owner: 'Process Owner', duration: '1 hour' },
            { id: 2, step: 'Execute', description: 'Perform main activities', owner: 'Team Lead', duration: '2 days' },
            { id: 3, step: 'Complete', description: 'Finalize and deliver', owner: 'Quality Assurance', duration: '4 hours' }
          ]
        };
      }
      return null;
    }
  },
  
  contextualResponses: (userMessage, currentData) => {
    const lowerMessage = userMessage.toLowerCase();
    
    // Check for form filling requests
    if (lowerMessage.includes('fill') && (lowerMessage.includes('example') || lowerMessage.includes('sample'))) {
      return "I'll fill in a complete example for you! This will give you a Customer Onboarding Process example that you can modify to fit your needs.";
    }
    
    if (lowerMessage.includes('clear') || lowerMessage.includes('reset')) {
      return "I'll clear all the form data so you can start fresh with your own process.";
    }
    
    // Check completion status and provide contextual guidance
    if (lowerMessage.includes('next') || lowerMessage.includes('what should i do')) {
      if (!currentData.processName) {
        return "Let's start with the basics! First, define your process name. What specific process are you analyzing? For example: 'Customer Onboarding Process' or 'Invoice Processing'. Or I can fill in example data if you'd like to see how it works!";
      }
      
      if (!currentData.processOwner) {
        return "Great! Now let's identify the process owner. Who is ultimately responsible for this process? This should be someone who has authority to make changes and improvements.";
      }
      
      if (currentData.suppliers && currentData.suppliers.length === 1 && !currentData.suppliers[0].name) {
        return "Now let's work on suppliers. Who provides the inputs to your process? Think about both internal departments and external vendors. Start with the most critical suppliers first. Need examples? Just ask!";
      }
      
      if (currentData.inputs && currentData.inputs.length === 1 && !currentData.inputs[0].name) {
        return "Time to define your inputs! What materials, information, or resources does your process need to function? Consider both tangible items and intangible things like approvals or data.";
      }
      
      if (currentData.process && currentData.process.length === 1 && !currentData.process[0].step) {
        return "Let's map out your process steps! Aim for 5-7 high-level steps that show the main flow. Don't get too detailed - focus on the major activities that transform inputs into outputs.";
      }
      
      if (currentData.outputs && currentData.outputs.length === 1 && !currentData.outputs[0].name) {
        return "Now for the outputs! What does your process produce? This could be products, services, information, or decisions. Think about what your customers receive from this process.";
      }
      
      if (currentData.customers && currentData.customers.length === 1 && !currentData.customers[0].name) {
        return "Finally, let's identify your customers! Who receives the outputs from your process? Remember, customers can be internal (other departments) or external (end users).";
      }
      
      return "You're making great progress! Review each section and add more detail where needed. Consider the relationships between suppliers, inputs, process steps, outputs, and customers. Need me to fill in more examples?";
    }
    
    return null;
  }
};

// Other tool configurations...
export const fishboneConfig = {
  title: "Fishbone AI Guide",
  welcomeMessage: "Welcome to Fishbone Diagram analysis! I'll help you identify root causes using the 6M method (Man, Machine, Material, Method, Measurement, Environment). I can also fill in example data. What problem are you trying to solve?",
  inputPlaceholder: "Ask me about root cause analysis, categories, problem definition, or say 'fill example data'...",
  
  responses: {
    'problem': "Start with a clear problem statement. Be specific about what's happening, when it occurs, and its impact. For example: 'Customer complaints increased by 30% in Q3' rather than just 'customer complaints'.",
    'man': "The 'Man' category covers people-related causes. Consider: training gaps, skill levels, communication issues, workload, motivation, or human error. Think about both individual and team factors.",
    'machine': "Machine/Equipment causes include: equipment failures, maintenance issues, capacity limitations, age of equipment, calibration problems, or technology gaps. Consider both hardware and software.",
    'material': "Material causes involve: quality issues, supplier problems, specifications, availability, storage conditions, or compatibility. Think about all inputs to your process.",
    'method': "Method/Process causes include: unclear procedures, missing steps, inefficient workflows, lack of standards, or process variations. Consider how work gets done.",
    'measurement': "Measurement causes involve: data accuracy, measurement tools, metrics definition, reporting frequency, or analysis methods. Consider how you track and measure performance.",
    'environment': "Environment causes include: physical conditions, workplace layout, organizational culture, regulations, market conditions, or external factors affecting your process."
  },
  
  defaultResponse: "I can help you explore root causes using the 6M categories: Man, Machine, Material, Method, Measurement, and Environment. Which category would you like to explore? I can also fill in example data!",
  
  quickActions: [
    { label: "Define Problem", message: "How do I write a good problem statement?" },
    { label: "6M Categories", message: "Explain the 6M categories" },
    { label: "Find Root Causes", message: "How do I identify root causes?" },
    { label: "Prioritize Causes", message: "How do I prioritize potential causes?" }
  ]
};

