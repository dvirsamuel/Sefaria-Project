import os
import glob
import pickle
import pandas as pd
import warnings

from classes import DataManager, Predictor, Categorizer, Evaluator
from datetime import datetime
from sklearn.svm import SVC, LinearSVC
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer, HashingVectorizer
from skmultilearn.problem_transform import LabelPowerset, BinaryRelevance, ClassifierChain

start_time = datetime.now()

# ignore warnings regarding column assignment, 
# e.g. df['col1'] = list1 -- not 100% sure about this
pd.options.mode.chained_assignment = None  # default='warn'

# do not limit num of rows in df to display
pd.set_option('display.max_rows', None)

# disable future warnings
warnings.simplefilter(action='ignore', category = FutureWarning)

# width of column to dispaly in dataframe
pd.options.display.max_colwidth = 40

# ******************************************************************************************************

def time_keeper(start_time):

    current_time = datetime.now()

    time_taken = current_time - start_time

    print(time_taken)

    return current_time


def refresh_scores():

    folders = ['/persistent/Sefaria-Project/ML/images/scores/*','images/cm/*']

    for folder in folders:
            
        files = glob.glob(folder)

        for f in files:

            os.remove(f)

    with open("/persistent/Sefaria-Project/ML/images/scores/scores_key.txt", "w") as file_object:

        file_object.write("scores_key")
    

def record_expt_specs(expt_num, vectorizer, classifier):

    with open("/persistent/Sefaria-Project/ML/images/scores/scores_key.txt", "a") as file_object:

        file_object.write(f'\n')

        file_object.write(f'\nexpt_num: {expt_num}')

        file_object.write(f'\nvectorizer: {vectorizer}')

        file_object.write(f'\nclassifier: {classifier}')

        file_object.write(f'\nsuper_topics: {super_topics}')

# ******************************************************************************************************

DATA_PATH = '/persistent/Sefaria-Project/ML/data/concat_english_prefix_hebrew.csv'

# classifier = BinaryRelevance(classifier=LinearSVC())
classifier = LabelPowerset(classifier=LinearSVC())
# classifier = ClassifierChain(classifier=LinearSVC())

# vectorizers = [HashingVectorizer(),CountVectorizer()]
vectorizer = CountVectorizer()

topic_groups_list = {}

div_laws_options = ['laws_united','laws_divided']

if False:
# if True:

    for i, div_laws in enumerate(div_laws_options):
        
        with open(f'/persistent/Sefaria-Project/ML/data/topic_groups_{div_laws_options[i]}.pickle', 'rb') as handle:

            topic_groups_list[i] = pickle.load(handle)

super_topics_list = [
    # ['history'],
    ['philosophy', 'places', 'biblical-figures', 'history', 'food', 'art', 'beliefs', 'health', 'prayer', 'nature', 'torah-portions', 'values', 'holidays', 'ritual-objects', 'lifecycle', 'stories', 'supernatural', 'social-issues', 'halachic-principles', 'human-ethics', 'family-law', 'laws-of-prayer', 'laws-of-kindness', 'property-law', 'tort-law', 'laws-of-impurity-and-purity', 'agricultural-law', 'laws-of-food', 'laws-of-clothing', 'noahide-(gentile)-law'],
    # ['philosophy', 'places', 'biblical-figures', 'history', 'laws', 'food', 'art', 'beliefs', 'health', 'prayer', 'nature', 'torah-portions', 'values', 'holidays', 'ritual-objects', 'lifecycle', 'stories', 'supernatural', 'social-issues'],
    # ['occurent', 'specifically-dependent-continuant','independent-continuant', 'generically-dependent-continuant'],
    # ['generically-dependent-continuant', 'independent-continuant','occurent', 'quality', 'realizable-entity']
]

super_topics = super_topics_list[0]

# langs_to_vec = ['eng', 'both']
lang_to_vec = 'eng' # ['eng','heb', 'both']

row_lim = None
# row_lim = 20000

max_children = 10

min_occurrences = 1

true_family_given = False

refresh_scores()

expt_num = 0

use_rules = False

use_ML = True

if True:    

    expt_num += 1

    record_expt_specs(expt_num, vectorizer, classifier)

    start_time = time_keeper(start_time)

    print('DataManager')
    
    data = DataManager(
        row_lim = row_lim, 
        data_path = DATA_PATH, 
        lang_to_vec = lang_to_vec, 
        should_stem = False, 
        super_topics = sorted(super_topics), # very impt to preserve order, e.g. alphabetical
        should_clean = True, 
        should_remove_stopwords = False,
        )

    data.prepare_dataframe()    

    start_time = time_keeper(start_time)

    print('Categorizer')
    
    categorizer = Categorizer(
        df = data.df, 
        super_topics = data.super_topics
        )

    categorizer.sort_children(
        max_children = max_children, 
        min_occurrences = min_occurrences
        )

    start_time = time_keeper(start_time)
    
    print('Predictor')
    
    predictor = Predictor(
        df = categorizer.df,
        use_rules = use_rules,
        use_ML = use_ML,
        classifier = classifier,
        vectorizer = vectorizer,
        true_family_given = true_family_given,
        topic_lists = categorizer.topic_lists,
        super_topics = categorizer.super_topics + ['entity'],
        )

    predictor.calc_results()

    start_time = time_keeper(start_time)
    
    print('Evaluator')
    
    evaluator = Evaluator(
        expt_num = expt_num, 
        data_sets = predictor.data_sets, 
        topic_lists = categorizer.topic_lists,
        super_topics = predictor.super_topics, 
        true_family_given = true_family_given,
        topic_counts = categorizer.topic_counts,
    ) 

    evaluator.calc_cm()

    evaluator.calc_scores()
    
    # evaluator.check_worst()

    start_time = time_keeper(start_time)

    # with open("images/scores/scores_key.txt", "a") as file_object:

    #     file_object.write(f'\ntime_taken: {time_taken}')

    print()

print()
