# from src.models.compendium.api import DnDAPI


# class TestAPI:

#     def test_api_request(self):
#         """
#         _summary_

#         Returns:
#             _type_: _description_
#         """
#         resources = [['search'], ['monsters'], ['spells', 'magicitems'], ['weapons', 'magicitems']]
#         for resource in resources:
#             results = DnDAPI.api_request()
            
#             assert results.get('results')
#             assert results.get('count') >= 0
            
            
#             results = DnDAPI.api_request(resource)
#             #
#             assert results.get('results')
#             assert results.get('count') >= 0
            

#             results = DnDAPI.api_request(resource, search="fire")
#             #
#             assert results.get('results')
#             assert results.get('count') >= 0
            
            
#             results = DnDAPI.api_request(resource, search="djydkdkuculkc")
#             #
#             assert not results['results']
            
#     def test_url_builder(self):
#         """
#         _summary_

#         Returns:
#             _type_: _description_
#         """
#         #test requesting all records
#         url = DnDAPI._build_general_search_url()
#         #
#         assert url == "https://api.open5e.com/search/?text="

#         #test requesting search of all records
#         url = DnDAPI._build_general_search_url("fire")
#         #
#         assert url == "https://api.open5e.com/search/?text=fire"

#         #test requesting all resources
#         url = DnDAPI._build_resource_search_url('monsters', search="fire")
#         assert url == "https://api.open5e.com/monsters/?search=fire"

#         #test requesting search of specific resource records
#         url = DnDAPI._build_resource_search_url('spells', search="fire")
#         #
#         assert url == "https://api.open5e.com/spells/?search=fire"

#         #test requesting search of specific resource records by filtered key/value pairs
#         url = DnDAPI._build_keyword_search_url('magicitems', name="a", type="b")
#         #
#         assert url == "https://api.open5e.com/magicitems/?name=a&type=b"
        
        
#     def test_response(self):
#         """
#         _summary_

#         Returns:
#             _type_: _description_
#         """
#         ########### TEST EMPTY ###########
#         test_result = {}
#         results = DnDAPI._response(test_result)
#         #
#         assert not results['results']
#         assert not results['count']
#         assert not results['next']

#         ########### TEST 0 ###########
#         resource_test ={
#             'results':[{"test_a":1}, {"test_b":2}]
#             }    
#         test_result['test0'] = resource_test
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == [{"test_a":1}, {"test_b":2}]
#         assert results['count'] == 2
#         assert not results['next']

#         ########### TEST 1 ###########
#         resource_test ={
#             'results':[{"test_c":1}, {"test_d":2}],
#             }
#         test_result['test1'] = resource_test
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == [{"test_a":1}, {"test_b":2}, {"test_c":1}, {"test_d":2}]
#         assert results['count'] == 4
#         assert not results['next']

#         ########### TEST 2 ###########
#         resource_test ={
#             'results':[{"test_e":1}, {"test_f":2}],
#             'count': 10,
#         }
#         test_result['test2'] = resource_test
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == [{"test_a":1}, {"test_b":2}, {"test_c":1}, {"test_d":2},  {"test_e":1}, {"test_f":2}]
#         assert results['count'] == 14
#         assert not results['next']


#          ########### TEST 3 ###########
#         resource_test ={
#             'results':[{"test_h":1}, {"test_i":2}],
#             'next' : "example_next_url",
#         }
#         test_result['test3'] = resource_test
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == [{"test_a":1}, {"test_b":2}, {"test_c":1}, {"test_d":2}, {"test_e":1}, {"test_f":2}, {"test_h":1}, {"test_i":2}]
#         assert results['count'] == 16
#         assert results['next'] == ["example_next_url"]
        
#          ########### TEST 4 ###########
#         resource_test ={
#             'results':[{"test_j":1}, {"test_k":2}],
#             'next' : "another_example_next_url",
#         }
#         test_result['test4'] = resource_test
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == [
#             {"test_a":1}, {"test_b":2}, {"test_c":1}, 
#             {"test_d":2}, {"test_e":1}, {"test_f":2},
#             {"test_h":1}, {"test_i":2}, {"test_j":1}, 
#             {"test_k":2},
#             ]
#         assert results['count'] == 18
#         assert results['next'] == ["example_next_url", "another_example_next_url"]

#         ########### TEST 5 ###########
#         resource_test ={
#             'results':[{"test_i":1}],
#             'count': 5,
#             'next' : "yet another example next url",
#         }
#         test_result['test5'] = resource_test
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == [
#             {"test_a":1}, {"test_b":2}, {"test_c":1}, 
#             {"test_d":2}, {"test_e":1}, {"test_f":2},
#             {"test_h":1}, {"test_i":2}, {"test_j":1}, 
#             {"test_k":2}, {"test_i":1}
#             ]
#         assert results['count'] == 23
#         assert results['next'] == ["example_next_url", "another_example_next_url", "yet another example next url"]

#         ########### TEST 6 ###########
#         test_result = {"test6":{"count":5, "next":"something"}}
#         results = DnDAPI._response(test_result)
        
#         assert results['results'] == []
#         assert results['count'] == 5
#         assert results['next'] == ["something"]