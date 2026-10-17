from types import SimpleNamespace
import pytest
import performance


class Response:
    ok=True
    def __init__(self,data):self.data=data
    def json(self):return self.data


def connector(scope='https://www.googleapis.com/auth/youtube.readonly'):
    return SimpleNamespace(token=lambda _:('private-test-token',{'channel_id':'mine','account':'Test channel','scope':scope}))


def test_basic_measurements_preserve_unknowns_and_do_not_request_extra_scope(monkeypatch):
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        if url.endswith('/channels'):return Response({'items':[{'id':'mine','contentDetails':{'relatedPlaylists':{'uploads':'uploads'}}}]})
        if url.endswith('/playlistItems'):return Response({'items':[{'contentDetails':{'videoId':'abcdefghijk'}}]})
        return Response({'items':[{'id':'abcdefghijk','snippet':{'channelId':'mine','title':'Real upload'},'statistics':{'viewCount':'123'},'contentDetails':{'duration':'PT30S'}}]})
    monkeypatch.setattr(performance.requests,'get',get)
    result=performance.performance(connector(),'youtube',10,28,True)
    assert result['videos'][0]['lifetime']=={'viewCount':123,'likeCount':None,'commentCount':None}
    assert result['analytics']['available'] is False
    assert not any('youtubeanalytics' in url for url in calls)
    assert 'private-test-token' not in str(result)


def test_published_edit_preserves_unrelated_fields_and_checks_owner(monkeypatch):
    writes=[]
    snippet={'channelId':'mine','title':'Old title','description':'Old text','categoryId':'22','tags':['keep me'],'defaultLanguage':'en','defaultAudioLanguage':'en','localized':{'title':'Read only'}}
    monkeypatch.setattr(performance.requests,'get',lambda *a,**k:Response({'items':[{'id':'abcdefghijk','etag':'unchanged','snippet':snippet}]}))
    monkeypatch.setattr(performance.requests,'put',lambda url,**kwargs:writes.append(kwargs) or Response({'id':'abcdefghijk'}))
    connect=connector(performance.YT_EDIT)
    result=performance.update_youtube_video(connect,'abcdefghijk','New title','New description','unchanged')
    assert result['id']=='abcdefghijk' and len(writes)==1
    saved=writes[0]['json'];assert saved['snippet']['tags']==['keep me'] and saved['snippet']['categoryId']=='22'
    assert 'status' not in saved and 'localized' not in saved['snippet']
    assert writes[0]['headers']['If-Match']=='unchanged'
    with pytest.raises(ValueError,match='changed'):
        performance.update_youtube_video(connect,'abcdefghijk','New','Caption','stale')
    assert len(writes)==1
    other=SimpleNamespace(token=lambda _:('token',{'channel_id':'other','scope':performance.YT_EDIT}))
    with pytest.raises(ValueError,match='does not belong'):
        performance.youtube_video(other,'abcdefghijk')
    with pytest.raises(ValueError,match='Enable published-video'):
        performance.update_youtube_video(connector(),'abcdefghijk','New','Caption','unchanged')


def test_optional_analytics_report_maps_actual_columns(monkeypatch):
    def get(url,**kwargs):
        if '/v2/reports' in url:
            assert kwargs['params']['filters']=='video==abcdefghijk'
            return Response({'columnHeaders':[{'name':'video'},{'name':'views'},{'name':'averageViewDuration'}],'rows':[['abcdefghijk',12,21.3]]})
        if url.endswith('/channels'):return Response({'items':[{'id':'mine','contentDetails':{'relatedPlaylists':{'uploads':'uploads'}}}]})
        if url.endswith('/playlistItems'):return Response({'items':[{'contentDetails':{'videoId':'abcdefghijk'}}]})
        return Response({'items':[{'id':'abcdefghijk','snippet':{'channelId':'mine'},'statistics':{}}]})
    monkeypatch.setattr(performance.requests,'get',get)
    data=performance.performance(connector(performance.YT_ANALYTICS),'youtube',10,28,True)
    assert data['analytics']['available'] and data['analytics']['rows'][0]['averageViewDuration']==21.3


def test_instagram_token_errors_are_specific_without_exposing_provider_text(monkeypatch):
    class Rejected(Response):
        ok=False;status_code=400
    connect=SimpleNamespace(token=lambda _:('private-token',{'user_id':'123','account':'Test creator'}))
    monkeypatch.setattr(performance.requests,'get',lambda *args,**kwargs:Rejected({'error':{'code':190,'message':'private-token in private provider text'}}))
    with pytest.raises(ValueError,match='code 190') as caught:
        performance.performance(connect,'instagram',5)
    assert 'private-token' not in str(caught.value)
