# coding: utf-8
from __future__ import unicode_literals

from .common import InfoExtractor
from ..compat import compat_str
from ..utils import (
    ExtractorError,
    int_or_none,
    try_get,
    update_url_query
)


class LineLiveIE(InfoExtractor):
    _VALID_URL = r'https?://live.line.me/channels/(?P<channel_id>\d+)/' \
        r'(?P<link_type>broadcast|upcoming)/(?P<id>\d+)'
    _TESTS = [
        # TEST 0 - archived broadcast via broadcast link
        {
            'url': 'https://live.line.me/channels/21/broadcast/7862238',
            'md5': 'b1de4d986fa10e462e57ad19bf2f2da0',
            'info_dict': {
                'id': '21_7862238',
                'ext': 'mp4',
                'title': '欅坂46 菅井友香・長濱ねる 初の２ショットラインライブ',
                'description': compat_str,
                'timestamp': 1522506855,
                'upload_date': '20180331',
                'duration': 1713,
                'uploader': 'LIVE チャンネル',
                'uploader_id': '21',
                'view_count': int,
                'comment_count': int,
                'is_live': False,
            }
        },
        # TEST 1 - archived broadcast via upcoming link
        {
            'url': 'https://live.line.me/channels/21/upcoming/8694200',
            'md5': 'a25e86f968aa89a6e18febe20cc49e44',
            'info_dict': {
                'id': '21_8656158',
                'ext': 'mp4',
                'title': '佐々木彩夏のAYAKA NATION 2018グッズ公開SP',
                'description': compat_str,
                'timestamp': 1529503261,
                'upload_date': '20180620',
                'duration': 4060,
                'uploader': 'LIVE チャンネル',
                'uploader_id': '21',
                'view_count': int,
                'comment_count': int,
                'is_live': False,
            }
        },
    ]

    def _real_extract(self, url):
        # Extract channel ID and broadcast ID from URL and download the
        # web page
        channel_id = self._search_regex(self._VALID_URL, url, 'channel_id',
                                        group='channel_id')
        broadcast_id = self._match_id(url)
        # Combination of channel ID and broadcast ID uniquely identifies
        # the video
        video_id = '%s_%s' % (channel_id, broadcast_id)
        req = self._request_webpage(url, video_id)
        webpage = self._webpage_read_content(req, url, video_id)
        # Upcoming URL redirects to a broadcast URL for archived broadcasts.
        # Re-extract the broadcast ID if this is the case.
        # TODO: Handle upcoming links for hidden broadcasts. For these, the
        # upcoming link ultimately redirects to a not_found page. One of the
        # intermediate redirects will be a broadcast link though. Retrieving
        # intermediate redirects is currently not supported by the extractor.
        link_type = self._search_regex(self._VALID_URL, url, 'link_type',
                                       group='link_type')
        if link_type == 'upcoming':
            url = req.url
            if self._search_regex(self._VALID_URL, url, 'link_type',
                                  group='link_type') != 'broadcast':
                raise ExtractorError('Broadcast not found', expected=True)
            broadcast_id = self._match_id(url)
            video_id = '%s_%s' % (channel_id, broadcast_id)

        # Try retrieving the broadcast info via API
        broadcast_api_url = 'https://live-api.line-apps.com/app/v2/channel/' \
                            '%s/broadcast/%s' % (channel_id, broadcast_id)
        broadcast_info = self._download_json(broadcast_api_url, video_id,
                                             fatal=False)
        # Try retrieving the broadcast info from the web page if we were
        # not able to get it from the API
        if not broadcast_info or 'item' not in broadcast_info:
            broadcast_info_str = self._html_search_regex(
                r'data-broadcast="([^"]+)"', webpage, 'data-broadcast',
                default='null')
            broadcast_info = self._parse_json(broadcast_info_str, video_id)
        if broadcast_info is None or 'item' not in broadcast_info:
            raise ExtractorError('Broadcast not found', expected=True)

        # Determine if broadcast is live or not
        item = broadcast_info.get('item')
        is_live = item.get('liveStatus') == 'LIVE'

        # Extract the stream URLs
        # First, try getting the live URLs directly from the API
        hls_urls = broadcast_info.get('liveHLSURLs')
        # Next, try getting the archived URLs directly from the API
        if hls_urls is None or hls_urls.get('abr') is None:
            hls_urls = broadcast_info.get('archivedHLSURLs')
        # Finally, use the lsaPath value to look up the stream URLs via the
        # LSS API. This should run when the broadcast is hidden or if we had
        # to get the broadcast info from the webpage.
        if hls_urls is None or hls_urls.get('abr') is None:
            lsa_path = broadcast_info.get('lsaPath')
            stream_type = 'live' if is_live else 'vod'
            lss_api_url = ('https://lssapi.line-apps.com/v1/%s/playInfo'
                           % stream_type)
            lss_api_url = update_url_query(lss_api_url,
                                           {'contentId': lsa_path})
            lss_info = self._download_json(lss_api_url, video_id, fatal=False)
            hls_urls = lss_info.get('playUrls') if lss_info else None
        if hls_urls is None or hls_urls.get('abr') is None:
            archive_status = item.get('archiveStatus')
            raise ExtractorError('Broadcast has an archive status of %s'
                                 % archive_status, expected=True)

        # Get the manifest URL and extract its formats
        manifest_url = hls_urls.get('abr')
        formats = self._extract_m3u8_formats(manifest_url, video_id, ext='mp4',
                                             entry_protocol='m3u8_native',
                                             m3u8_id='hls', live=is_live)
        self._sort_formats(formats)

        # Extract video metadata
        title = item.get('title') or self._og_search_title(webpage)
        timestamp = item.get('createdAt')
        view_count = item.get('viewerCount')
        comment_count = item.get('chatCount')
        duration = item.get('archiveDuration')
        uploader = try_get(item, lambda x: x['channel']['name'], compat_str)
        uploader_url = 'https://live.line.me/channels/%s' % channel_id
        description = (broadcast_info.get('description') or
                       self._og_search_description(webpage))
        thumbnail = try_get(item, lambda x: x['thumbnailURLs']['large1x1'],
                            compat_str) or self._og_search_thumbnail(webpage)

        if is_live:
            title = self._live_title(title)

        # Return the video info
        return {
            'id': video_id,
            'title': title,
            'description': description,
            'thumbnail': thumbnail,
            'timestamp': int_or_none(timestamp),
            'duration': duration,
            'uploader': uploader,
            'uploader_id': channel_id,
            'uploader_url': uploader_url,
            'view_count': int_or_none(view_count),
            'comment_count': int_or_none(comment_count),
            'formats': formats,
            'is_live': is_live,
        }
