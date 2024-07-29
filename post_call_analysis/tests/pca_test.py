#!/usr/bin/env python3
"""
Post Call Analysis (PCA) Test Script

This script tests the functionality of the Post Call Analysis using unittest.
It loads transcripts and tests the analysis capabilities.

Usage:
    python tests/pca_test.py

Returns:
    0 if all tests pass, or a positive integer representing the number of failed tests.
"""

import os
import sys
import shutil
import time
import unittest
import logging
from typing import List, Dict, Any
import glob
import pandas as pd
import yaml

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Setup paths and global variables
current_dir = os.getcwd()
kit_dir = current_dir
repo_dir = os.path.abspath(os.path.join(kit_dir, ".."))
logger.info(f'kit_dir: {kit_dir}')
logger.info(f'repo_dir: {repo_dir}')

sys.path.append(kit_dir)
sys.path.append(repo_dir)

from post_call_analysis.src import analysis, plot, asr

def load_test_config(config_path):
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

test_config = load_test_config(kit_dir+'/tests/test_config.yaml')
transcription_path = os.path.join(kit_dir, test_config['paths']['transcription_path'])
transcription=pd.read_csv(transcription_path)
facts_path = os.path.join(kit_dir, test_config['paths']['facts_path'])
procedures_path =  os.path.join(kit_dir, test_config['paths']['procedures_path'])
facts_urls = []
classes = test_config["classes"]
entities = test_config["entities"]
sentiments = test_config["sentiments"]

def convert_to_dialogue_structure(transcription):
    dialogue = ''  
    for _, row in transcription.iterrows():
        speaker = str(row['speaker'])
        text = str(row['text'])
        dialogue += speaker + ': ' + text + '\n'   
    return dialogue

class PCATestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.time_start = time.time()
        cls.dialogue = cls.convertToDialogueStructure()
        cls.conversation = cls.loadConversation()
        cls.conversation_chunks = cls.getChunks()
        cls.result=cls.callAnalysisParallel()
    
    @classmethod
    def convertToDialogueStructure(cls):
        dialogue = convert_to_dialogue_structure(transcription)
        return dialogue
    
    @classmethod
    def loadConversation(cls):
        conversation = analysis.load_conversation(cls.dialogue, transcription_path)
        return conversation
    
    @classmethod
    def getChunks(cls):
        conversation_chunks = analysis.get_chunks(cls.conversation)
        return conversation_chunks
    
    @classmethod
    def callAnalysisParallel(cls):
        result=analysis.call_analysis_parallel(cls.conversation_chunks, documents_path=facts_path, facts_urls=facts_urls, procedures_path=procedures_path, classes_list=classes, entities_list=entities, sentiment_list=sentiments)
        return result
    
    # Add assertions
    def test_load_conversation(self):
        self.assertTrue(self.conversation[0].metadata, "Metadata shouldn't be empty")
        self.assertTrue(self.conversation[0].page_content, "Page content shouldn't be empty")

    def test_get_chunks(self):
        self.assertTrue(len(self.conversation_chunks) > 0, "There should be at least one conversation chunk")

    def test_conversation_summary(self):
        logger.info("\nConversation summary:")
        logger.info(self.result["summary"])
        self.assertTrue(self.result["summary"], "Summary is empty")

    def test_classification(self):
        logger.info("\nClassification:")
        logger.info(self.result["classification"][0])
        self.assertIn(self.result["classification"][0], classes, "Invalid classification value")
    
    def test_sentiment_analysis(self):
        logger.info("\nSentiment analysis:")
        logger.info(self.result["sentiment"])
        self.assertIn(self.result["sentiment"], sentiments, "Invalid sentiment value")

    def test_NPS_prediction(self):
        logger.info("\nNPS prediction:")
        logger.info(self.result["nps_analysis"])
        logger.info("Predicted NPS: %d"%(self.result['nps_score']))
        self.assertTrue(self.result["nps_analysis"], "NPS analysis is empty")
        self.assertIsInstance(self.result["nps_score"], int,"NPS score is not an integer")
    
    def test_factual_accuracy_analysis(self):
        logger.info("\nFactual accuracy analysis:")
        logger.info("correct: %s"%(self.result["factual_analysis"]['correct']))
        logger.info("errors: %s"%(self.result["factual_analysis"]['errors']))
        self.assertIsInstance(self.result["factual_analysis"]["correct"], bool, "Factual analysis 'correct' is not a boolean")
    
    def test_procedures_analysis(self):
        logger.info("\nProcedures analysis")
        logger.info("correct: %s"%(self.result["procedural_analysis"]['correct']))
        logger.info("errors: %s"%(self.result["procedural_analysis"]['errors']))
        self.assertIsInstance(self.result["procedural_analysis"]["correct"], bool, "Procedural analysis 'correct' is not a boolean")

    def test_NER(self):
        entities_items = self.result["entities"].items()
        logger.info(entities_items)
        for key in self.result["entities"].keys():
            self.assertIn(key, entities, f"Invalid entity key: {key}")

    def test_call_quality_assessment(self):
        logger.info("\nCall quality assessment:")
        logger.info(self.result["quality_score"])
        self.assertIsInstance(self.result["quality_score"], float, "Call quality score is not a float")

    @classmethod
    def tearDownClass(cls):
        time_end = time.time()
        total_time = time_end - cls.time_start
        logger.info(f"Total execution time: {total_time:.2f} seconds")   
    
class CustomTextTestResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_results: List[Dict[str, Any]] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.test_results.append({"name": test._testMethodName, "status": "PASSED"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.test_results.append({"name": test._testMethodName, "status": "FAILED", "message": str(err[1])})

    def addError(self, test, err):
        super().addError(test, err)
        self.test_results.append({"name": test._testMethodName, "status": "ERROR", "message": str(err[1])})

def main():
    suite = unittest.TestLoader().loadTestsFromTestCase(PCATestCase)
    test_result = unittest.TextTestRunner(resultclass=CustomTextTestResult).run(suite)

    logger.info("\nTest Results:")
    for result in test_result.test_results:
        logger.info(f"{result['name']}: {result['status']}")
        if 'message' in result:
            logger.info(f"  Message: {result['message']}")

    failed_tests = len(test_result.failures) + len(test_result.errors)
    logger.info(f"\nTests passed: {test_result.testsRun - failed_tests}/{test_result.testsRun}")

    if failed_tests:
        logger.error(f"Number of failed tests: {failed_tests}")
        return failed_tests
    else:
        logger.info("All tests passed successfully!")
        return 0
    
if __name__ == "__main__":
    sys.exit(main())